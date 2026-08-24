"""Offline entity bridge index builder (design D1/D4/D5).

Idempotent per-KB full rebuild: extract entities from every active document
(title as the highest-weight source, then a content prefix), accumulate the
inverted postings, compute doc_freq, and mark generic entities by the
statistical criterion ``doc_freq / kb_doc_count > threshold`` (no
vocabularies).  Online query paths never call this module.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import AsyncIterator

from sqlalchemy import text

from entity_index.extractors import get_extractor

# 单文档参与抽取的正文前缀长度（标题已提供主实体，正文前缀补足共现信号）
DEFAULT_CONTENT_CHARS = 2000
# 单实体串入库长度上限（列宽 256，留余量）
MAX_ENTITY_LEN = 255
# postings 批量写入大小
POSTING_BATCH = 5000


@dataclass(frozen=True)
class BuildStats:
    kb_id: str
    documents: int
    entities: int
    generic_entities: int
    postings: int


async def build_entity_index(
    kb_id: uuid.UUID,
    *,
    generic_df_percent: int,
    extractor_name: str = "rule_v1",
    content_chars: int = DEFAULT_CONTENT_CHARS,
) -> BuildStats:
    """Rebuild the entity index for one knowledge base (idempotent)."""
    from core.source.postgres import PostgresConfig
    from sqlalchemy.ext.asyncio import create_async_engine

    extractor = get_extractor(extractor_name)
    engine = create_async_engine(PostgresConfig.from_env().async_connection)

    # 实体 -> 文档集合（内存累积；评测库规模 10 万级文档可承载）
    entity_docs: dict[str, set[uuid.UUID]] = defaultdict(set)
    doc_count = 0

    try:
        async with engine.connect() as conn:
            stream: AsyncIterator = await conn.stream(
                text(
                    "SELECT id, title, left(content, :n) AS body "
                    "FROM rag.rag_documents "
                    "WHERE knowledge_base_id = :kb AND status = 'active'"
                ),
                {"kb": kb_id, "n": content_chars},
            )
            async for row in stream:
                doc_count += 1
                entities: set[str] = set()
                if row.title:
                    entities |= extractor.extract(str(row.title))
                if row.body:
                    entities |= extractor.extract(str(row.body))
                for entity in entities:
                    entity = entity[:MAX_ENTITY_LEN]
                    if entity:
                        entity_docs[entity].add(row.id)
        if doc_count == 0:
            raise ValueError(f"knowledge base {kb_id} has no active documents")

        threshold = max(1, int(doc_count * generic_df_percent / 100))

        async with engine.begin() as conn:
            # 幂等覆盖：先清空该 kb 既有索引行
            await conn.execute(
                text("DELETE FROM rag.entity_index_postings WHERE kb_id = :kb"),
                {"kb": kb_id},
            )
            await conn.execute(
                text("DELETE FROM rag.entity_index_entities WHERE kb_id = :kb"),
                {"kb": kb_id},
            )

            entity_rows = []
            posting_rows = []
            generic_count = 0
            for entity, docs in entity_docs.items():
                doc_freq = len(docs)
                is_generic = doc_freq > threshold
                if is_generic:
                    generic_count += 1
                entity_rows.append((kb_id, entity, doc_freq, is_generic))
                for doc_id in docs:
                    posting_rows.append((kb_id, entity, doc_id))

            for start in range(0, len(entity_rows), POSTING_BATCH):
                await conn.execute(
                    text(
                        "INSERT INTO rag.entity_index_entities "
                        "(kb_id, entity, doc_freq, is_generic) "
                        "VALUES (:kb, :entity, :df, :generic)"
                    ),
                    [
                        {"kb": kb_id, "entity": e, "df": df, "generic": g}
                        for (kb_id, e, df, g) in entity_rows[start : start + POSTING_BATCH]
                    ],
                )
            for start in range(0, len(posting_rows), POSTING_BATCH):
                await conn.execute(
                    text(
                        "INSERT INTO rag.entity_index_postings "
                        "(kb_id, entity, document_id) "
                        "VALUES (:kb, :entity, :doc)"
                    ),
                    [
                        {"kb": kb_id, "entity": e, "doc": d}
                        for (kb_id, e, d) in posting_rows[start : start + POSTING_BATCH]
                    ],
                )

        return BuildStats(
            kb_id=kb_id.hex,
            documents=doc_count,
            entities=len(entity_docs),
            generic_entities=generic_count,
            postings=len(posting_rows),
        )
    finally:
        await engine.dispose()
        # 重建后立即失效进程内缓存，避免在线路径读到旧索引
        try:
            from entity_index.store import invalidate_entity_bundle

            invalidate_entity_bundle(kb_id.hex)
        except Exception:
            pass
