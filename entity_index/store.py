"""Query-time entity index access (design D2/D6).

Loads the offline-built inverted index from PG into per-KB bundles with a
small LRU cache; online paths call ``load_entity_bundle`` and degrade
silently when the index is missing.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy import text

# 进程内缓存的 KB 数上限：16 覆盖跨多库会话/评测脚本轮流访问多库的场景，
# 原值 2 会在多库间来回切换时反复淘汰、缓存抖动失效；索引重建时仍主动失效
_BUNDLE_LRU_MAX = 16
_bundles: "OrderedDict[str, EntityBundle]" = OrderedDict()
# 按 KB 维度的装载互斥锁：同一 KB 并发首查只构建一次，
# 不同 KB 的加载互不阻塞（全局单锁会把跨库扇出完全串行化）
_load_locks: "OrderedDict[str, asyncio.Lock]" = OrderedDict()
_LOAD_LOCK_MAX = 64


@dataclass(frozen=True)
class EntityBundle:
    postings: dict[str, tuple[str, ...]]  # entity -> document_ids
    doc_entities: dict[str, tuple[str, ...]]  # document_id -> entities
    generic: frozenset[str]  # 统计判据判定的通用实体


def invalidate_entity_bundle(kb_id: str | None = None) -> None:
    """Drop cached bundles (called after index rebuilds).

    缓存键统一为带连字符的 str(uuid.UUID(...))（与 load_entity_bundle 的键
    同一规范形）：调用方可能传 kb_id.hex（无连字符），须先归一再失效，
    否则键永不相等、失效静默落空。
    """
    if kb_id is None:
        _bundles.clear()
        return
    try:
        key = str(uuid.UUID(str(kb_id)))
    except (ValueError, AttributeError):
        key = str(kb_id)
    _bundles.pop(key, None)


def _load_lock_for(key: str) -> asyncio.Lock:
    """取（惰性创建）该 KB 的装载锁；少量淘汰防止锁表无界增长。"""
    lock = _load_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _load_locks[key] = lock
        while len(_load_locks) > _LOAD_LOCK_MAX:
            _load_locks.popitem(last=False)
    else:
        _load_locks.move_to_end(key)
    return lock


async def load_entity_bundle(kb_id: uuid.UUID | str) -> EntityBundle | None:
    """Load (and cache) the entity index bundle for one KB.

    Returns None when the index tables hold no rows for the KB (index not
    built) — callers degrade gracefully.
    """
    from database.postgre_client import get_async_engine

    key = str(kb_id)
    cached = _bundles.get(key)
    if cached is not None:
        _bundles.move_to_end(key)
        return cached

    kb_uuid = uuid.UUID(key) if isinstance(key, str) else kb_id
    # 进程级共享引擎（连接池），避免每次加载重建引擎/dispose 的开销
    engine = get_async_engine()
    # 同一 KB 并发首查只构建一次（消除 check-then-set 竞态下的重复建载）
    async with _load_lock_for(key):
        cached = _bundles.get(key)
        if cached is not None:
            _bundles.move_to_end(key)
            return cached
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
