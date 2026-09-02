"""
既有知识库 sparse 向量迁移（fastembed 英文 tokenizer → jieba 中文 BM25）。

原理：混合集合的 dense 向量与 payload 与编码器无关，仅 sparse 命名向量需要
重算。脚本读 PG 叶块文本 → 目标编码器编码 → Qdrant update_vectors 仅更新
sparse 部分（dense/payload 保留，不重新调用 embedding 服务）。

用法：
  uv run python utils/migrate_sparse.py --list                    # 列出全部知识库与叶块数
  uv run python utils/migrate_sparse.py --kb-id <uuid>            # 迁移指定库（默认 jieba）
  uv run python utils/migrate_sparse.py --kb-id <uuid> --batch 500
  uv run python utils/migrate_sparse.py --kb-id <uuid> --encoder legacy   # 回滚到旧编码
"""

import argparse
import asyncio
import sys
import uuid
from typing import Any, Callable

from sqlalchemy import select, text

# 允许从任意工作目录运行
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.postgre_client import get_session
from database.qdrant_client import QdrantManager, SPARSE_VECTOR_NAME
from entity.rag.chunks import Chunk
from entity.rag.document import Document
from entity.rag.knowledge_base import KnowledgeBase
from qdrant_client.models import PointVectors

DEFAULT_BATCH = 1000


def _pick_encoder(encoder: str) -> tuple[str, Callable]:
    """返回 (编码器名, embed_documents 函数)。"""
    if encoder == "jieba":
        from model.sparse.bm25 import embed_documents as fn

        return "jieba", fn
    if encoder == "legacy":
        from model.sparse.bm25 import legacy_embed_documents as fn

        return "legacy", fn
    raise SystemExit(f"未知编码器: {encoder}（可选 jieba / legacy）")


async def list_kbs() -> None:
    """列出全部知识库（排除软删除）与叶块数。"""
    async with get_session() as session:
        kbs = (
            (
                await session.execute(
                    select(KnowledgeBase).where(KnowledgeBase.status != "deleted")
                )
            )
            .scalars()
            .all()
        )
        for kb in kbs:
            doc_ids = (
                (
                    await session.execute(
                        select(Document.id).where(
                            Document.knowledge_base_id == kb.id,
                            Document.status != "deleted",
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not doc_ids:
                continue
            chunk_count = (
                await session.execute(
                    select(text("count(*)"))
                    .select_from(Chunk)
                    .where(
                        Chunk.document_id.in_(list(doc_ids)),
                        Chunk.level == 0,
                    )
                )
            ).scalar_one()
            print(
                f"{kb.id}  {kb.name}  {chunk_count} 叶块  collection={kb.qdrant_collection}"
            )


async def migrate_kb(kb_id: str, batch_size: int, encoder: str) -> None:
    """迁移单个知识库的 sparse 向量。"""
    name, embed_documents = _pick_encoder(encoder)
    kb_uuid = uuid.UUID(kb_id)

    async with get_session() as session:
        kb = await session.get(KnowledgeBase, kb_uuid)
        if kb is None:
            raise SystemExit(f"知识库不存在: {kb_id}")
        doc_ids = (
            (
                await session.execute(
                    select(Document.id).where(
                        Document.knowledge_base_id == kb_uuid,
                        Document.status != "deleted",
                    )
                )
            )
            .scalars()
            .all()
        )
        rows = (
            await session.execute(
                select(Chunk.id, Chunk.content)
                .where(Chunk.document_id.in_(list(doc_ids)))
                .where(Chunk.level == 0)
            )
        ).all()

    chunks = [(cid.hex, content or "") for cid, content in rows]
    print(f"[迁移] 知识库 {kb.name}（{kb.id.hex}）：{len(chunks)} 叶块，编码器={name}")

    manager = QdrantManager(kb.qdrant_collection)
    client = manager.client
    total = 0
    skipped = 0
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        sparse_vectors = await asyncio.to_thread(embed_documents, [t for _, t in batch])
        points = []
        for (cid, _), sv in zip(batch, sparse_vectors):
            if not sv.indices:  # 空分词点（全停用词）：update_vectors 拒绝空向量
                skipped += 1
                continue
            points.append(PointVectors(id=cid, vector={SPARSE_VECTOR_NAME: sv}))
        if points:
            await asyncio.to_thread(client.update_vectors, kb.qdrant_collection, points)
        total += len(batch)
        if total % (batch_size * 5) == 0 or total == len(chunks):
            print(f"[迁移] 进度 {total}/{len(chunks)}（跳过空分词 {skipped}）")
    print(f"[迁移] 完成：{kb.name}（{total} 叶块，跳过 {skipped} 空分词点）")


async def main() -> None:
    parser = argparse.ArgumentParser(description="既有知识库 sparse 向量迁移")
    parser.add_argument("--list", action="store_true", help="列出全部知识库与叶块数")
    parser.add_argument(
        "--kb-id", type=str, default=None, help="目标知识库 id（hex uuid）"
    )
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH, help="每批叶块数")
    parser.add_argument(
        "--encoder", choices=["jieba", "legacy"], default="jieba", help="目标编码器"
    )
    args = parser.parse_args()

    if args.list:
        await list_kbs()
        return
    if not args.kb_id:
        raise SystemExit("请指定 --kb-id（或 --list 查看全部知识库）")
    await migrate_kb(args.kb_id, args.batch, args.encoder)


if __name__ == "__main__":
    asyncio.run(main())
