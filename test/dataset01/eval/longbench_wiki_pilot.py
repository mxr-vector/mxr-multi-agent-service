"""LongBench topic-index pilot and 20-page semantic-purity audit.

Build reads the already-ingested LongBench documents from PostgreSQL and
materializes one independent topic collection.  Audit produces a deterministic
20-page checklist for human review; it never exposes source paragraphs in the
topic-page payload.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path

from common import RESULTS_DIR, ensure_cfg_async, save_json
from dual_retrieval import get_eval_session
from wiki.models import WikiDocument
from wiki.index import TopicIndexBuilder
from wiki.storage import TopicPageStore
from wiki.vectors import DocumentVector, build_document_vectors

PILOT_SCOPE = "longbench-v3"
PILOT_RESULT_PATH = RESULTS_DIR / "longbench_wiki_pilot.json"
AUDIT_PATH = RESULTS_DIR / "longbench_wiki_purity_audit.json"


async def load_documents(kb_ids: list[str], limit: int | None = None) -> list[WikiDocument]:
    from entity.rag.document import Document
    from sqlalchemy import select

    parsed_ids = [uuid.UUID(value) for value in kb_ids]
    async with get_eval_session() as session:
        stmt = (
            select(Document)
            .where(Document.knowledge_base_id.in_(parsed_ids))
            .where(Document.status == "active")
            .order_by(Document.id)
        )
        if limit:
            stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
    return [
        WikiDocument(
            document_id=doc.id.hex,
            title=doc.title or doc.source_uri or doc.id.hex,
            metadata={
                **(doc.doc_metadata or {}),
                "source_system": doc.source_system,
                "source_uri": doc.source_uri,
                "knowledge_base_id": doc.knowledge_base_id.hex,
            },
            # The pilot uses only a representative prefix. Topic pages never
            # receive this content; it is used solely for document vectors.
            representative_blocks=((doc.content or "")[:4000],),
            content=doc.content or "",
            version=doc.version,
            knowledge_base_id=doc.knowledge_base_id.hex,
        )
        for doc in rows
    ]


def load_existing_vectors(kb_hex: str) -> dict[str, tuple[float, ...]]:
    """Aggregate already-ingested leaf-chunk dense vectors per document.

    Libraries built by the corpus pipeline already carry embeddings in their
    evidence collection; averaging them yields document-level topic vectors
    without re-embedding. Returns an empty mapping when the collection is
    absent so callers fall back to factory embedding.
    """
    import numpy as np
    from database.qdrant_client import DENSE_VECTOR_NAME, QdrantManager, build_kb_collection_name

    manager = QdrantManager(build_kb_collection_name(uuid.UUID(kb_hex)))
    if not manager.client.collection_exists(manager.collection):
        return {}
    sums: dict[str, np.ndarray] = {}
    counts: dict[str, int] = {}
    offset = None
    while True:
        batch, offset = manager.client.scroll(
            collection_name=manager.collection,
            limit=256,
            offset=offset,
            with_vectors=[DENSE_VECTOR_NAME],
            with_payload=["document_id"],
        )
        for point in batch:
            vectors = point.vector if isinstance(point.vector, dict) else {DENSE_VECTOR_NAME: point.vector}
            dense = vectors.get(DENSE_VECTOR_NAME)
            document_id = (point.payload or {}).get("document_id")
            if dense is None or not document_id:
                continue
            array = np.asarray(dense, dtype=np.float64)
            sums[document_id] = sums.get(document_id, 0.0) + array
            counts[document_id] = counts.get(document_id, 0) + 1
        if offset is None or not batch:
            break
    return {
        document_id: tuple((sums[document_id] / counts[document_id]).tolist())
        for document_id in sums
    }


def reuse_document_vectors(
    documents: list[WikiDocument], reused: dict[str, tuple[float, ...]]
) -> list[DocumentVector] | None:
    """Combine reused vectors with factory embedding for the uncovered docs."""
    if not reused:
        return None
    vectors: list[DocumentVector] = []
    missing: list[WikiDocument] = []
    for document in documents:
        vector = reused.get(document.document_id)
        if vector is None:
            missing.append(document)
            continue
        vectors.append(
            DocumentVector(document=document, text=document.title or document.document_id, vector=vector)
        )
    if missing:
        vectors.extend(build_document_vectors(missing))
    return vectors


async def build_pilot(
    kb_ids: list[str],
    *,
    scope_id: str = PILOT_SCOPE,
    limit: int | None = None,
    offline_generation: bool = False,
    resume: bool = False,
    reuse_vectors: bool = True,
) -> dict:
    await ensure_cfg_async()
    generator = (lambda prompt: {}) if offline_generation else None
    builder = TopicIndexBuilder()
    # Production lookup is scoped by the request's knowledge-base ids. The
    # default pilot therefore writes one independent collection per library;
    # an explicit --scope-id can still build one intentional aggregate.
    per_library = scope_id == PILOT_SCOPE
    build_scopes = kb_ids if per_library else [scope_id]
    scope_records = []
    document_count = 0
    created_at = datetime.now(timezone.utc).isoformat()

    def payload(complete: bool) -> dict:
        return {
            "scope_id": scope_id,
            "created_at": created_at,
            "complete": complete,
            "document_count": document_count,
            "page_count": sum(record["page_count"] for record in scope_records),
            "cluster_stats": [record["cluster_stats"] for record in scope_records],
            "noise_policy": [record["cluster_stats"].get("noise_policy") for record in scope_records],
            "version": [record["version"] for record in scope_records],
            "collections": [TopicPageStore(record["scope_id"]).collection for record in scope_records],
            "library_scopes": [record["scope_id"] for record in scope_records],
            "offline_generation": offline_generation,
            "resumed": resume,
        }

    for index_scope in build_scopes:
        documents = await load_documents([index_scope] if per_library else kb_ids, limit)
        if not documents:
            continue
        document_count += len(documents)
        store = TopicPageStore(index_scope)
        if resume and not store.is_empty():
            pages = store.list_pages()
            stats = {
                "documents": len(documents),
                "clusters": len(pages),
                "resumed_existing": True,
            }
            scope_records.append(
                {
                    "scope_id": index_scope,
                    "page_count": len(pages),
                    "cluster_stats": stats,
                    "version": max((page.version for page in pages), default=1),
                }
            )
            save_json(PILOT_RESULT_PATH, payload(complete=False))
            print(f"[wiki] resumed existing scope {index_scope}: {len(pages)} pages")
            continue

        reused = load_existing_vectors(index_scope) if reuse_vectors and per_library else {}
        vectors = reuse_document_vectors(documents, reused)
        print(
            f"[wiki] scope {index_scope}: {len(reused)} docs reuse evidence vectors"
            + (f", {len(documents) - len(reused)} fall back to embedding" if vectors else "")
        )
        result = await builder.build(
                documents,
                index_scope,
                generator=generator,
                recreate=True,
                vectors=vectors,
            )
        scope_records.append(
            {
                "scope_id": result.scope_id,
                "page_count": len(result.pages),
                "cluster_stats": result.clusters.stats,
                "version": result.version,
            }
        )
        save_json(PILOT_RESULT_PATH, payload(complete=False))
        print(f"[wiki] completed scope {result.scope_id}: {len(result.pages)} pages")
    if not scope_records:
        raise SystemExit("No active LongBench documents found for the supplied knowledge-base ids")
    result_payload = payload(complete=True)
    save_json(PILOT_RESULT_PATH, result_payload)
    print(f"[wiki] pilot complete: {result_payload}")
    return result_payload


def audit_pages(scope_id: str | None = None, sample_size: int = 20) -> dict:
    scopes = [scope_id] if scope_id else []
    if not scopes and PILOT_RESULT_PATH.exists():
        scopes = list(json.loads(PILOT_RESULT_PATH.read_text(encoding="utf-8")).get("library_scopes") or [])
    if not scopes:
        scopes = [PILOT_SCOPE]
    pages = [
        (scope, page)
        for scope in scopes
        for page in TopicPageStore(scope).list_pages()
    ]
    if not pages:
        raise SystemExit("Wiki topic collection is empty; run the pilot build first")
    sample_size = min(sample_size, len(pages))
    rng = random.Random(42)
    sample = sorted(rng.sample(pages, sample_size), key=lambda item: (item[0], item[1].topic_id))
    payload = {
        "scope_id": scope_id,
        "sample_size": len(sample),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "instructions": "Review topic coherence, navigation-only boundary, and representative questions. Fill pass/reason.",
        "pages": [
            {
                "scope_id": scope,
                "topic_id": page.topic_id,
                "title": page.title,
                "summary": page.summary,
                "keywords": list(page.keywords),
                "entities": list(page.entities),
                "representative_questions": list(page.representative_questions),
                "document_count": len(page.documents),
                "dirty": page.dirty,
                "pass": None,
                "reason": "",
            }
            for scope, page in sample
        ],
    }
    save_json(AUDIT_PATH, payload)
    print(f"[wiki] audit checklist written: {AUDIT_PATH}")
    return payload


async def main() -> None:
    parser = argparse.ArgumentParser(description="LongBench LLM Wiki pilot")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--kb-ids", required=True, help="comma-separated LongBench knowledge-base UUIDs")
    build.add_argument("--scope-id", default=PILOT_SCOPE)
    build.add_argument("--max-documents", type=int, default=None)
    build.add_argument("--offline-generation", action="store_true")
    build.add_argument("--resume", action="store_true", help="reuse non-empty per-library topic collections")
    build.add_argument("--no-reuse-vectors", action="store_true", help="embed document vectors from scratch")
    audit = sub.add_parser("audit")
    audit.add_argument("--scope-id", default=None)
    audit.add_argument("--sample-size", type=int, default=20)
    args = parser.parse_args()
    if args.command == "build":
        await build_pilot(
            [item.strip() for item in args.kb_ids.split(",") if item.strip()],
            scope_id=args.scope_id,
            limit=args.max_documents,
            offline_generation=args.offline_generation,
            resume=args.resume,
            reuse_vectors=not args.no_reuse_vectors,
        )
    else:
        audit_pages(args.scope_id, args.sample_size)


if __name__ == "__main__":
    asyncio.run(main())
