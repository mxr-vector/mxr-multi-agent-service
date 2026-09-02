"""Query-time entity index access (design D2/D6).

Loads the offline-built inverted index from PG into per-KB bundles with a
small LRU cache; online paths call ``load_entity_bundle`` and degrade
silently when the index is missing.
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
    postings: dict[str, tuple[str, ...]]  # entity -> document_ids
    doc_entities: dict[str, tuple[str, ...]]  # document_id -> entities
    generic: frozenset[str]  # 统计判据判定的通用实体


def invalidate_entity_bundle(kb_id: str | None = None) -> None:
    """Drop cached bundles (called after index rebuilds)."""
    if kb_id is None:
        _bundles.clear()
    else:
        _bundles.pop(str(kb_id), None)


async def load_entity_bundle(kb_id: uuid.UUID | str) -> EntityBundle | None:
    """Load (and cache) the entity index bundle for one KB.

    Returns None when the index tables hold no rows for the KB (index not
    built) — callers degrade gracefully.
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
