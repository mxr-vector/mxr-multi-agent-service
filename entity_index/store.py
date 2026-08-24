"""Query-time entity index access (design D2/D6).

Loads the offline-built inverted index from PG into per-KB bundles with a
small LRU cache; online paths call ``load_entity_bundle`` and degrade
silently when the index is missing.  Two fetch paths feed the expansion
channel: entity-anchored leaf chunks per (document, entity) provenance, and
wiki chunk pointers resolved by chunk id.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy import text

# 进程内缓存的 KB 数上限（评测/单库对话场景够用；索引重建时主动失效）
_BUNDLE_LRU_MAX = 2
_bundles: "OrderedDict[str, EntityBundle]" = OrderedDict()


@dataclass(frozen=True)
class EntityBundle:
    postings: dict[str, tuple[str, ...]]      # entity -> document_ids
    doc_entities: dict[str, tuple[str, ...]]  # document_id -> entities
    generic: frozenset[str]                   # 统计判据判定的通用实体


def invalidate_entity_bundle(kb_id: str | None = None) -> None:
    """Drop cached bundles (called after index rebuilds)."""
    if kb_id is None:
        _bundles.clear()
    else:
        _bundles.pop(str(kb_id), None)


async def load_entity_bundle(kb_id: uuid.UUID | str) -> EntityBundle | None:
    """Load (and cache) the entity index bundle for one KB.

    Returns None when the index tables hold no rows for the KB (index not
    built) — callers treat that as "no expansion channel".
    """
    from core.source.postgres import PostgresConfig
    from sqlalchemy.ext.asyncio import create_async_engine

    key = str(kb_id)
    cached = _bundles.get(key)
    if cached is not None:
        _bundles.move_to_end(key)
        return cached

    kb_uuid = uuid.UUID(key) if isinstance(key, str) else kb_id
    engine = create_async_engine(PostgresConfig.from_env().async_connection)
    try:
        async with engine.connect() as conn:
            entity_rows = (
                await conn.execute(
                    text(
                        "SELECT entity, is_generic FROM rag.entity_index_entities "
                        "WHERE kb_id = :kb"
                    ),
                    {"kb": kb_uuid},
                )
            ).all()
            if not entity_rows:
                return None
            posting_rows = (
                await conn.execute(
                    text(
                        "SELECT entity, document_id FROM rag.entity_index_postings "
                        "WHERE kb_id = :kb"
                    ),
                    {"kb": kb_uuid},
                )
            ).all()
    finally:
        await engine.dispose()

    generic = frozenset(row.entity for row in entity_rows if row.is_generic)
    postings: dict[str, list[str]] = {}
    doc_entities: dict[str, list[str]] = {}
    for row in posting_rows:
        doc_id = str(row.document_id)
        postings.setdefault(row.entity, []).append(doc_id)
        doc_entities.setdefault(doc_id, []).append(row.entity)
    bundle = EntityBundle(
        postings={e: tuple(docs) for e, docs in postings.items()},
        doc_entities={d: tuple(ents) for d, ents in doc_entities.items()},
        generic=generic,
    )
    _bundles[key] = bundle
    while len(_bundles) > _BUNDLE_LRU_MAX:
        _bundles.popitem(last=False)
    return bundle


async def fetch_expansion_chunks_by_ids(
    chunk_ids: list[str],
    limit: int,
) -> list[dict]:
    """Fetch leaf chunks by id (wiki page chunk pointers resolve to original
    text here — no online document-to-chunk guessing).  Output shape matches
    ``fetch_expansion_chunks`` so both feed the same expansion channel."""
    if not chunk_ids:
        return []
    from core.source.postgres import PostgresConfig
    from sqlalchemy.ext.asyncio import create_async_engine

    chunk_uuids = []
    for chunk_id in chunk_ids[:limit]:
        try:
            chunk_uuids.append(uuid.UUID(str(chunk_id)))
        except ValueError:
            continue
    if not chunk_uuids:
        return []
    engine = create_async_engine(PostgresConfig.from_env().async_connection)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, document_id, content FROM rag.rag_chunks "
                        "WHERE id = ANY(:ids) AND level = 0"
                    ),
                    {"ids": chunk_uuids},
                )
            ).all()
    finally:
        await engine.dispose()
    return [
        {
            "document_id": row.document_id.hex,
            "chunk_id": row.id.hex,
            "text": row.content or "",
            "score": 0.0,
        }
        for row in rows
    ]


def select_entity_chunk(
    doc_chunks: list[dict],
    entity: str | None,
) -> dict | None:
    """Pick the leaf chunk of one document that carries the bridging entity.

    The first chunk whose content contains the entity (case-insensitive) is
    preferred — bridge paragraphs often live mid-document, so the document's
    first chunk is only the fallback.  ``doc_chunks`` must be ordered by
    chunk_index.  Mirrored offline by ``wiki.pointers.pick_representative_
    chunk`` (page-entity anchoring over a different chunk schema).
    """
    if not doc_chunks:
        return None
    if entity:
        key = entity.casefold()
        for chunk in doc_chunks:
            if key in (chunk.get("text") or "").casefold():
                return chunk
    return doc_chunks[0]


async def fetch_expansion_chunks(
    targets: list[tuple[str, str | None]],
    limit: int,
) -> list[dict]:
    """Fetch one leaf chunk per expanded document, anchored to its entity.

    ``targets`` are (document_id, entity) provenance pairs from
    ``link_and_expand``: the chunk containing that entity is preferred over
    the document's first chunk (bridge paragraphs are often mid-document).
    Text comes from PG rag_chunks (Qdrant payloads carry no chunk text);
    document_id is globally unique, so no KB filter is needed.
    """
    if not targets:
        return []
    from core.source.postgres import PostgresConfig
    from sqlalchemy.ext.asyncio import create_async_engine

    doc_uuids = []
    uuid_of: dict[str, str] = {}
    for doc_id, _entity in targets[:limit]:
        try:
            doc_uuids.append(uuid.UUID(str(doc_id)))
            uuid_of[str(doc_uuids[-1])] = str(doc_id)
        except ValueError:
            continue
    if not doc_uuids:
        return []
    engine = create_async_engine(PostgresConfig.from_env().async_connection)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT document_id, id, content "
                        "FROM rag.rag_chunks "
                        "WHERE document_id = ANY(:docs) AND level = 0 "
                        "ORDER BY document_id, chunk_index"
                    ),
                    {"docs": list(doc_uuids)},
                )
            ).all()
    finally:
        await engine.dispose()

    by_doc: dict[str, list[dict]] = {}
    for row in rows:
        by_doc.setdefault(str(row.document_id), []).append(
            {
                # 输出统一为无连字符 hex：主路候选/评测 gold 均用该格式，
                # 带连字符 UUID 会在终排合并去重与 gold 匹配两处静默失配
                "document_id": row.document_id.hex,
                "chunk_id": str(row.id),
                "text": row.content or "",
                "score": 0.0,
            }
        )
    entity_of = {str(doc_id): (entity or None) for doc_id, entity in targets}
    selected = []
    for doc_uuid, doc_id in uuid_of.items():
        chunks = by_doc.get(doc_uuid)
        if not chunks:
            continue
        chunk = select_entity_chunk(chunks, entity_of.get(doc_id))
        selected.append({**chunk, "expansion_entity": entity_of.get(doc_id)})
    return selected
