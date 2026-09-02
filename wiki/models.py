"""Data contracts for the LLM Wiki topic index."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


def _value(record: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(record, dict) and name in record:
            return record[name]
        if hasattr(record, name):
            return getattr(record, name)
    return default


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return _as_text(value) or datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class WikiDocument:
    """Document-level input for vector construction and topic generation."""

    document_id: str
    title: str = ""
    metadata: dict = field(default_factory=dict)
    content: str = ""
    representative_blocks: tuple[str, ...] = ()
    version: int = 1
    knowledge_base_id: str | None = None

    @classmethod
    def from_record(cls, record: Any) -> "WikiDocument":
        blocks = _value(
            record,
            "representative_blocks",
            "representative_chunks",
            "blocks",
            default=(),
        )
        if isinstance(blocks, str):
            blocks = (blocks,)
        elif blocks is None:
            blocks = ()
        else:
            normalized = []
            for block in blocks:
                if isinstance(block, dict):
                    block = block.get("content", block.get("text", ""))
                elif hasattr(block, "content"):
                    block = block.content
                if _as_text(block):
                    normalized.append(_as_text(block))
            blocks = tuple(normalized)

        metadata = _value(record, "metadata", "doc_metadata", default={}) or {}
        if not isinstance(metadata, dict):
            metadata = {"value": _as_text(metadata)}
        document_id = _value(record, "document_id", "id")
        if document_id is None:
            raise ValueError("wiki document requires document_id/id")
        return cls(
            document_id=str(document_id),
            title=_as_text(_value(record, "title", default="")),
            metadata=dict(metadata),
            content=_as_text(_value(record, "content", default="")),
            representative_blocks=blocks,
            version=int(_value(record, "version", default=1) or 1),
            knowledge_base_id=(
                str(_value(record, "knowledge_base_id"))
                if _value(record, "knowledge_base_id") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class TopicPage:
    """Navigation-only topic page stored in the independent wiki collection."""

    topic_id: str
    title: str
    summary: str
    keywords: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    representative_questions: tuple[str, ...] = ()
    documents: tuple[str, ...] = ()
    # 成员文档的代表性叶块 id（离线锚定：含页面实体的块优先）。查询期按
    # id 直查原文，替代在线"文档→块"猜测；仅存 id，不落块内容
    chunks: tuple[str, ...] = ()
    related_topics: tuple[str, ...] = ()
    version: int = 1
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    dirty: bool = False
    coarse_partition: str | None = None

    @property
    def search_text(self) -> str:
        return "\n".join(
            part
            for part in (
                self.title,
                self.summary,
                " ".join(self.keywords),
                " ".join(self.entities),
                " ".join(self.representative_questions),
            )
            if part
        )

    def to_payload(self) -> dict:
        """Serialize only navigation fields; never include source paragraphs."""
        return {
            "topic_id": self.topic_id,
            "title": self.title,
            "summary": self.summary,
            "keywords": list(self.keywords),
            "entities": list(self.entities),
            "representative_questions": list(self.representative_questions),
            "documents": list(self.documents),
            "chunks": list(self.chunks),
            "related_topics": list(self.related_topics),
            "version": self.version,
            "updated_at": self.updated_at,
            "dirty": self.dirty,
            "coarse_partition": self.coarse_partition,
            "text": self.search_text,
        }

    def to_dict(self) -> dict:
        return self.to_payload()

    @classmethod
    def from_payload(cls, payload: dict, *, topic_id: str | None = None) -> "TopicPage":
        payload = payload or {}
        return cls(
            topic_id=str(payload.get("topic_id") or topic_id or ""),
            title=_as_text(payload.get("title")),
            summary=_as_text(payload.get("summary")),
            keywords=tuple(str(value) for value in payload.get("keywords") or []),
            entities=tuple(str(value) for value in payload.get("entities") or []),
            representative_questions=tuple(
                str(value) for value in payload.get("representative_questions") or []
            ),
            documents=tuple(str(value) for value in payload.get("documents") or []),
            chunks=tuple(str(value) for value in payload.get("chunks") or []),
            related_topics=tuple(
                str(value) for value in payload.get("related_topics") or []
            ),
            version=int(payload.get("version") or 1),
            updated_at=_iso(payload.get("updated_at")),
            dirty=bool(payload.get("dirty", False)),
            coarse_partition=(
                str(payload["coarse_partition"])
                if payload.get("coarse_partition") is not None
                else None
            ),
        )


def topic_page_from_mapping(mapping: dict, *, topic_id: str | None = None) -> TopicPage:
    """Public helper used by persistence adapters and tests."""
    return TopicPage.from_payload(mapping, topic_id=topic_id)
