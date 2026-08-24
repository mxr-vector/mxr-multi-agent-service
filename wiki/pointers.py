"""Offline chunk-pointer attachment for wiki topic pages.

Pages store document-level membership; query time then has to guess which
leaf chunk of each member document is the evidence.  This module moves that
guess offline: for every member document it anchors the representative leaf
chunk (first chunk containing a page entity, case-insensitive; fallback
first chunk) and writes the chunk id into ``TopicPage.chunks`` so online
retrieval resolves wiki hits to original text by id, deterministically.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

from wiki.models import TopicPage

# 每页块指针上限：大簇成员众多，控制页 payload 体积；成员序即聚置信序
MAX_CHUNKS_PER_PAGE = 20


def pick_representative_chunk(
    doc_chunks: list[dict],
    entities: tuple[str, ...],
) -> dict | None:
    """First leaf chunk containing a page entity, else the first chunk.

    ``doc_chunks`` must be ordered by chunk_index.  Mirrors the online
    anchoring rule (``entity_index.store.select_entity_chunk``) so offline
    pointers and online fallback behave identically.
    """
    if not doc_chunks:
        return None
    for entity in entities:
        key = entity.casefold()
        if not key:
            continue
        for chunk in doc_chunks:
            if key in (chunk.get("content") or "").casefold():
                return chunk
    return doc_chunks[0]


async def attach_chunk_pointers(
    pages: list[TopicPage],
    kb_hex: str,
    *,
    cap: int = MAX_CHUNKS_PER_PAGE,
) -> list[TopicPage]:
    """Attach representative chunk ids to pages (one KB's page set).

    Fetches level-0 chunks of all member documents from PG in batched
    queries; pages without member chunks keep an empty pointer list and the
    online doc-anchor fallback continues to apply to them.
    """
    from sqlalchemy import text

    from core.source.postgres import PostgresConfig
    from sqlalchemy.ext.asyncio import create_async_engine

    if not pages:
        return pages
    engine = create_async_engine(PostgresConfig.from_env().async_connection)
    updated: list[TopicPage] = []
    batch = 200  # 每批成员文档数，控制 ANY() 数组与单次返回体积
    try:
        async with engine.connect() as conn:
            for start in range(0, len(pages), batch):
                window = pages[start : start + batch]
                doc_ids: list[str] = []
                for page in window:
                    doc_ids.extend(page.documents)
                doc_uuids = []
                for doc_id in doc_ids:
                    try:
                        doc_uuids.append(uuid.UUID(str(doc_id)))
                    except ValueError:
                        continue
                if not doc_uuids:
                    updated.extend(window)
                    continue
                rows = (
                    await conn.execute(
                        text(
                            "SELECT document_id, id, content FROM rag.rag_chunks "
                            "WHERE document_id = ANY(:docs) AND level = 0 "
                            "ORDER BY document_id, chunk_index"
                        ),
                        {"docs": doc_uuids},
                    )
                ).all()
                by_doc: dict[str, list[dict]] = {}
                for row in rows:
                    by_doc.setdefault(row.document_id.hex, []).append(
                        {"id": row.id.hex, "content": row.content or ""}
                    )
                for page in window:
                    entities = page.entities or page.keywords
                    picked: list[str] = []
                    for doc_id in page.documents:
                        if len(picked) >= cap:
                            break
                        chunks = by_doc.get(str(doc_id).replace("-", ""))
                        if not chunks:
                            continue
                        picked.append(pick_representative_chunk(chunks, entities)["id"])
                    updated.append(replace(page, chunks=tuple(picked)))
    finally:
        await engine.dispose()
    return updated
