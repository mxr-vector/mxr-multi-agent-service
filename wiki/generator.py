"""Navigation-only topic page generation."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Sequence

from pydantic import BaseModel, Field

from wiki.clustering import TopicCluster
from wiki.models import TopicPage


class TopicPageDraft(BaseModel):
    """LLM output schema for one complete topic page."""

    title: str = Field(description="Short topic title")
    summary: str = Field(description="Navigation-level summary without source evidence")
    keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    representative_questions: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
    related_topics: list[str] = Field(default_factory=list)


def _tokens(values: Sequence[str], limit: int = 12) -> list[str]:
    counts: dict[str, int] = {}
    for value in values:
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u3400-\u9fff]{2,}", value or ""):
            counts[token.casefold()] = counts.get(token.casefold(), 0) + 1
    return [key for key, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _fallback_draft(cluster: TopicCluster, related_topics: Sequence[str]) -> TopicPageDraft:
    titles = [item.document.title for item in cluster.document_vectors if item.document.title]
    keywords = _tokens(titles)
    title = titles[0] if titles else f"Topic {cluster.cluster_id}"
    if len(title) > 80:
        title = title[:80].rstrip()
    questions = [f"What is covered by {title}?", f"Which documents relate to {title}?"]
    return TopicPageDraft(
        title=title,
        summary=f"Navigation index for {len(cluster.document_vectors)} related documents about {title}.",
        keywords=keywords,
        entities=keywords[:8],
        representative_questions=questions,
        documents=cluster.document_ids,
        related_topics=list(related_topics),
    )


def _parse_json_object(text: str) -> dict | None:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.IGNORECASE).strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except (TypeError, ValueError):
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except (TypeError, ValueError):
            return None


def _normalize_draft(data: dict) -> dict:
    """Coerce common LLM output quirks into the draft schema.

    Models frequently echo ``documents`` back as the input records
    ({"id": ..., "title": ...}) instead of bare id strings.
    """
    normalized = dict(data)
    for key in ("documents", "related_topics", "keywords", "entities", "representative_questions"):
        values = normalized.get(key)
        if isinstance(values, list):
            normalized[key] = [
                item.get("id") if isinstance(item, dict) and item.get("id") is not None else item
                for item in values
            ]
    return normalized


def _prompt(cluster: TopicCluster, related_topics: Sequence[str]) -> str:
    # Titles and metadata labels are enough for navigation.  Deliberately do
    # not send representative block contents to the page generator.
    records = [
        {
            "id": item.document.document_id,
            "title": item.document.title,
            "metadata": item.document.metadata,
        }
        for item in cluster.document_vectors
    ]
    # Large clusters would force the model to echo dozens of ids back, which
    # frequently truncates the JSON; sample the records and keep the id list
    # short — the page keeps the full cluster membership regardless.
    truncated_note = ""
    if len(records) > 40:
        truncated_note = (
            f"\nNote: {len(records)} documents total; only a representative "
            "subset is shown. For documents return [] and we will fill it "
            "from the full cluster membership."
        )
        records = records[:40]
    return (
        "Generate a navigation-only topic page for the following document cluster. "
        "Do not quote source text, answer questions, or include sensitive values. "
        "Return every field in the requested schema. documents must preserve the "
        "provided ids. representative_questions are typical offline query phrasings.\n"
        f"cluster_id={cluster.cluster_id}\n"
        f"related_topics={list(related_topics)}\n"
        f"documents={records}{truncated_note}\n"
        "Respond with a single JSON object using fields: title, summary, "
        "keywords, entities, representative_questions, documents, related_topics."
    )


async def generate_topic_page(
    cluster: TopicCluster,
    *,
    version: int = 1,
    related_topics: Sequence[str] = (),
    generator: Callable[[str], Any] | Callable[[str], Awaitable[Any]] | None = None,
) -> TopicPage:
    """Generate one topic page with an injectable LLM boundary and fallback."""
    draft: TopicPageDraft | None = None
    if generator is None:
        try:
            from model.chat.factory import build_chat_model

            # Thinking mode rejects forced tool_choice and the server lacks
            # json_schema response format; ask for plain JSON and parse it.
            model = build_chat_model(temperature=0)

            async def generator(prompt: str):
                response = await model.ainvoke([{"role": "user", "content": prompt}])
                return _parse_json_object(str(getattr(response, "content", response))) or {}

        except Exception:
            generator = None
    if generator is not None:
        try:
            result = generator(_prompt(cluster, related_topics))
            if hasattr(result, "__await__"):
                result = await result
            if isinstance(result, TopicPageDraft):
                draft = result
            elif isinstance(result, dict):
                draft = TopicPageDraft.model_validate(_normalize_draft(result))
            else:
                draft = TopicPageDraft.model_validate(getattr(result, "model_dump", lambda: {})())
        except Exception:
            draft = None
    if draft is None:
        draft = _fallback_draft(cluster, related_topics)

    allowed_docs = set(cluster.document_ids)
    documents = tuple(dict.fromkeys(item for item in draft.documents if item in allowed_docs))
    if not documents:
        documents = tuple(cluster.document_ids)
    related = tuple(
        dict.fromkeys(
            value for value in draft.related_topics if value in set(related_topics)
        )
    )
    if not related:
        related = tuple(related_topics)
    return TopicPage(
        topic_id=cluster.cluster_id,
        title=draft.title.strip() or f"Topic {cluster.cluster_id}",
        summary=draft.summary.strip(),
        keywords=tuple(dict.fromkeys(value.strip() for value in draft.keywords if value.strip())),
        entities=tuple(dict.fromkeys(value.strip() for value in draft.entities if value.strip())),
        representative_questions=tuple(
            dict.fromkeys(value.strip() for value in draft.representative_questions if value.strip())
        ),
        documents=documents,
        related_topics=related,
        version=version,
        updated_at=datetime.now(timezone.utc).isoformat(),
        dirty=False,
        coarse_partition=cluster.coarse_partition,
    )


async def generate_topic_pages(
    clusters: Sequence[TopicCluster],
    *,
    version: int = 1,
    generator: Callable[[str], Any] | Callable[[str], Awaitable[Any]] | None = None,
    concurrency: int = 8,
) -> list[TopicPage]:
    """Generate pages concurrently (cluster order preserved) with stable hints."""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def one(cluster: TopicCluster, related: Sequence[str]) -> TopicPage:
        async with semaphore:
            return await generate_topic_page(
                cluster,
                version=version,
                related_topics=related,
                generator=generator,
            )

    tasks = [
        one(
            cluster,
            [
                other.cluster_id
                for other in clusters
                if other.cluster_id != cluster.cluster_id
            ][:5],
        )
        for cluster in clusters
    ]
    return list(await asyncio.gather(*tasks))
