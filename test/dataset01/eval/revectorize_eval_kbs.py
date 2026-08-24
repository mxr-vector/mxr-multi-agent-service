"""Rebuild Qdrant hybrid collections for eval KBs from PG leaf chunks.

Use when Qdrant storage was lost but PG documents/chunks survived: streams
leaf chunks from PG, re-embeds (dense via embedding factory) + re-encodes
sparse (jieba BM25), upserts with chunk id as point id and production-aligned
payloads.  Document ids are preserved, so the existing doc-map stays valid.

Usage:
  uv run python revectorize_eval_kbs.py            # doc_map 全部库
  uv run python revectorize_eval_kbs.py --kb-ids a,b
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

MAX_LEAVES_PER_UPSERT = 400


async def revectorize_kb(kb_hex: str, name: str) -> None:
    import uuid

    from database.postgre_client import get_session
    from database.qdrant_client import QdrantManager
    from entity.rag.chunks import Chunk
    from entity.rag.document import Document
    from entity.rag.knowledge_base import KnowledgeBase

    kb_uuid = uuid.UUID(kb_hex)
    async with get_session() as session:
        kb = await session.get(KnowledgeBase, kb_uuid)
        if kb is None:
            print(f"[revec] {name}: KB 不存在，跳过", flush=True)
            return
        doc_ids = (
            await session.execute(
                select(Document.id).where(
                    Document.knowledge_base_id == kb_uuid,
                    Document.status != "deleted",
                )
            )
        ).scalars().all()
        if not doc_ids:
            print(f"[revec] {name}: 无文档，跳过", flush=True)
            return
        # 分批 IN 查询：asyncpg 单语句参数上限 32767，大库分片拉取叶块
        rows: list = []
        for start in range(0, len(doc_ids), 8000):
            batch_ids = doc_ids[start : start + 8000]
            part = (
                await session.execute(
                    select(
                        Chunk.id,
                        Chunk.document_id,
                        Chunk.content,
                        Chunk.chapter_title,
                        Chunk.page_start,
                        Chunk.page_end,
                        Document.title,
                        Document.version,
                    )
                    .where(Chunk.document_id.in_(list(batch_ids)))
                    .where(Chunk.level == 0)
                    .join(Document, Chunk.document_id == Document.id)
                )
            ).all()
            rows.extend(part)

    manager = QdrantManager(kb.qdrant_collection)
    total = len(rows)
    print(f"[revec] {name}: {total} 叶块 → {kb.qdrant_collection}", flush=True)
    done = 0
    for start in range(0, total, MAX_LEAVES_PER_UPSERT):
        batch = rows[start : start + MAX_LEAVES_PER_UPSERT]
        texts = [row.content or "" for row in batch]
        payloads = [
            {
                "document_id": row.document_id.hex,
                "knowledge_base_id": kb_uuid.hex,
                "document_version": row.version,
                "chunk_id": row.id.hex,
                "chapter_title": row.chapter_title,
                "page_start": row.page_start,
                "page_end": row.page_end,
                "title": row.title,
            }
            for row in batch
        ]
        ids = [row.id.hex for row in batch]
        await asyncio.to_thread(manager.upsert_hybrid, texts, payloads, ids)
        done += len(batch)
        print(f"[revec] {name}: {done}/{total}", flush=True)
    print(f"[revec] {name}: 完成 {done} 叶块", flush=True)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb-ids", default="", help="逗号分隔；缺省为 doc_map 全部库")
    args = parser.parse_args()

    from common import ensure_cfg_async, load_json
    from longbench_eval import DOC_MAP_PATH

    await ensure_cfg_async()
    doc_map = load_json(DOC_MAP_PATH)
    kb_ids_map = doc_map.get("kb_ids") or {}
    if args.kb_ids:
        wanted = {k.strip() for k in args.kb_ids.split(",") if k.strip()}
        kb_ids_map = {
            name: kid
            for name, kid in kb_ids_map.items()
            if kid in wanted or name in wanted
        }
    for name, kid in kb_ids_map.items():
        await revectorize_kb(kid, name)


if __name__ == "__main__":
    asyncio.run(main())
