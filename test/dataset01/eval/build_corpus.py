"""
S1 建库：把农业维基 QA 110K 按维基页面聚合为文档，复用项目摄取链路
（ingest_file 两级切块 → Chunk 块树落 PG → Qdrant upsert_hybrid 向量化）
写入专用评测知识库（KB_NAME），与业务知识库隔离。

用法：
  uv run python test/dataset01/eval/build_corpus.py            # 建库（幂等：已存在则提示）
  uv run python test/dataset01/eval/build_corpus.py --force    # 已存在时重建（先清理再建）
  uv run python test/dataset01/eval/build_corpus.py --cleanup  # 整体删除评测知识库
  uv run python test/dataset01/eval/build_corpus.py --smoke    # 建库后抽样验证召回
  uv run python test/dataset01/eval/build_corpus.py --stats-only  # 仅输出数据集统计

注意：本阶段不依赖 CFG（无需模型角色配置），仅需 ENV + PG + Qdrant + embedding 服务。
"""

import argparse
import asyncio
import statistics
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select

from common import (
    CORPUS_STATS_PATH,
    DATASET_ROOT,
    KB_DESCRIPTION,
    KB_NAME,
    aggregate_by_page,
    ensure_csv,
    ensure_dirs,
    load_dataset,
    normalize,
    save_json,
    sha256_of_file,
)

# 每批向量化写入的文档数（决定进度打印粒度）
DEFAULT_BATCH_SIZE = 50
# 单次 upsert_hybrid 的叶块上限：dense 2560 维 ≈ 10KB/点 + payload 文本，
# 超出 Qdrant 单请求 32MB 上限会 400；按叶块数切分比文档数更稳
MAX_LEAVES_PER_UPSERT = 400


async def find_eval_kb(session):
    """按 KB_NAME 查评测知识库（含软删除，供清理兜底）。"""
    from entity.rag.knowledge_base import KnowledgeBase

    stmt = select(KnowledgeBase).where(KnowledgeBase.name == KB_NAME)
    result = await session.execute(stmt)
    return result.scalars().first()


async def create_eval_kb(session) -> object:
    """创建评测知识库行（dept_id=''，id/集合名由仓储派生）。"""
    from database.rag.knowledge_base import KnowledgeBaseRepository

    repo = KnowledgeBaseRepository(session)
    return await repo.create(
        name=KB_NAME,
        dept_id="",
        description=KB_DESCRIPTION,
        visibility="private",
        owner=None,
    )


async def ingest_page_document(
    session, kb, page: dict
) -> tuple[object, list[dict], int]:
    """
    单页面文档：聚合文本切块 → 两级块树落 PG（每文档一事务由调用方提交）。
    返回 (doc, leaf_specs, leaf_count)；leaf_specs 为向量化用
    [{text, payload, id}]，payload 与生产 vectorize_job 对齐并追加 pageid/title。
    """
    from database.rag.document import DocumentRepository
    from entity.rag.chunks import Chunk
    from utils.file_ingest import ingest_file

    text = page["text"].strip()
    if not text:
        return None, [], 0

    doc_repo = DocumentRepository(session)
    doc = await doc_repo.create(
        knowledge_base_id=kb.id,
        content=text,
        content_hash=sha256_of_text(text),
        doc_type="text",
        source_uri=f"wiki:{page['pageid']}",
        source_system="wikipedia-agriculture",
        title=page["title"] or f"wiki:{page['pageid']}",
        metadata={
            "pageid": page["pageid"],
            "url": page["url"],
            "qa_count": len(page["qa_pairs"]),
            "source_system": "wikipedia-agriculture",
        },
        status="active",
        dept_id="",
    )

    parsed = ingest_file(f"{page['pageid']}.txt", text.encode("utf-8"))
    parents = parsed["parents"]

    parent_chunks = [
        Chunk(
            document_id=doc.id,
            document_version=doc.version,
            level=1,
            chunk_index=p["chunk_index"],
            content=p["content"],
            parent_chunk_id=None,
            char_start=p["char_start"],
            char_end=p["char_end"],
            chapter_title=p["chapter_title"],
            page_start=p["page_start"],
            page_end=p["page_end"],
            content_hash=p["content_hash"],
            chunk_metadata={},
            dept_id="",
        )
        for p in parents
    ]
    await _bulk_insert_chunks(session, parent_chunks)

    leaf_specs: list[dict] = []
    leaf_chunks: list[Chunk] = []
    for parent_chunk, p in zip(parent_chunks, parents):
        for c in p["children"]:
            leaf_chunks.append(
                Chunk(
                    document_id=doc.id,
                    document_version=doc.version,
                    level=0,
                    chunk_index=c["chunk_index"],
                    content=c["content"],
                    parent_chunk_id=parent_chunk.id,
                    char_start=c["char_start"],
                    char_end=c["char_end"],
                    chapter_title=c["chapter_title"],
                    page_start=c["page_start"],
                    page_end=c["page_end"],
                    content_hash=c["content_hash"],
                    chunk_metadata={},
                    dept_id="",
                )
            )
    # 先落库拿到服务端生成的 id（= Qdrant point id），再装配向量化 specs
    await _bulk_insert_chunks(session, leaf_chunks)
    for leaf in leaf_chunks:
        leaf_specs.append(
            {
                "text": leaf.content,
                "payload": {
                    "document_id": doc.id.hex,
                    "knowledge_base_id": kb.id.hex,
                    "document_version": doc.version,
                    "chunk_id": leaf.id.hex,
                    "chapter_title": leaf.chapter_title,
                    "page_start": leaf.page_start,
                    "page_end": leaf.page_end,
                    "pageid": page["pageid"],
                    "title": page["title"],
                },
                "id": leaf.id.hex,
            }
        )
    return doc, leaf_specs, len(leaf_specs)


async def _bulk_insert_chunks(session, chunks) -> None:
    from database.rag.chunks import ChunkRepository

    await ChunkRepository(session).bulk_insert(chunks)


def sha256_of_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def vectorize_batch(kb, leaf_specs: list[dict]) -> None:
    """一批叶块写入 Qdrant（dense+sparse，同步 IO 丢线程池）。

    按 MAX_LEAVES_PER_UPSERT 切分为多次 upsert_hybrid，避免单请求
    payload 超过 Qdrant 32MB 上限（2560 维 dense 向量体积大）。
    """
    from database.qdrant_client import QdrantManager

    manager = QdrantManager(kb.qdrant_collection)
    for start in range(0, len(leaf_specs), MAX_LEAVES_PER_UPSERT):
        chunk = leaf_specs[start : start + MAX_LEAVES_PER_UPSERT]
        await asyncio.to_thread(
            manager.upsert_hybrid,
            [spec["text"] for spec in chunk],
            payloads=[spec["payload"] for spec in chunk],
            ids=[spec["id"] for spec in chunk],
        )


async def cleanup_eval_kb(session) -> int:
    """整体删除评测知识库：Qdrant 集合 + PG 块树 + 文档行 + 知识库行。返回删除的知识库数。"""
    from database.qdrant_client import QdrantManager
    from entity.rag.chunks import Chunk
    from entity.rag.document import Document
    from entity.rag.knowledge_base import KnowledgeBase

    kb = await find_eval_kb(session)
    if kb is None:
        return 0
    # 先删向量集合（与生产删除文档同序：先 Qdrant 后 PG，避免孤儿点可被检索）
    await asyncio.to_thread(QdrantManager(kb.qdrant_collection).delete_collection)
    doc_ids = (
        (
            await session.execute(
                select(Document.id).where(Document.knowledge_base_id == kb.id)
            )
        )
        .scalars()
        .all()
    )
    if doc_ids:
        await session.execute(delete(Chunk).where(Chunk.document_id.in_(list(doc_ids))))
        await session.execute(
            delete(Document).where(Document.knowledge_base_id == kb.id)
        )
    await session.execute(delete(KnowledgeBase).where(KnowledgeBase.id == kb.id))
    await session.commit()
    return 1


async def build_corpus(
    csv_path, batch_size: int, force: bool, smoke: bool, limit: int | None = None
) -> None:
    from database.postgre_client import get_session

    ensure_dirs()
    df = load_dataset(limit=limit)
    pages = aggregate_by_page(df)
    csv_sha256 = sha256_of_file(csv_path)

    async with get_session() as session:
        existing = await find_eval_kb(session)
        if existing is not None and not force:
            print(
                f"[S1] 评测知识库已存在: {KB_NAME} id={existing.id.hex} "
                f"collection={existing.qdrant_collection}（跳过建库）\n"
                f"      重建请加 --force（先清理再重建），删除请用 --cleanup"
            )
            return
        if existing is not None and force:
            print(f"[S1] --force：清理既有评测知识库 {KB_NAME}...")
            await cleanup_eval_kb(session)

        kb = await create_eval_kb(session)
        await session.commit()
        print(
            f"[S1] 已创建评测知识库: {KB_NAME} id={kb.id.hex} collection={kb.qdrant_collection}"
        )

        total_pages = len(pages)
        total_chunks = 0
        total_docs = 0
        doc_lengths: list[int] = []
        qa_per_page: list[int] = []
        pending_specs: list[dict] = []
        pending_pages = 0

        for idx, page in enumerate(pages, start=1):
            doc, leaf_specs, leaf_count = await ingest_page_document(session, kb, page)
            if doc is None:
                continue
            await session.commit()
            total_docs += 1
            total_chunks += leaf_count
            doc_lengths.append(len(page["text"]))
            qa_per_page.append(len(page["qa_pairs"]))
            pending_specs.extend(leaf_specs)
            pending_pages += 1

            # 每 batch 个文档向量化一次（含进度）
            if pending_pages >= batch_size:
                await vectorize_batch(kb, pending_specs)
                print(
                    f"[S1] 向量化 {pending_pages} 个文档 / {len(pending_specs)} 叶块 "
                    f"（{idx}/{total_pages} 页，累计叶块 {total_chunks}）"
                )
                pending_specs = []
                pending_pages = 0

        if pending_specs:
            await vectorize_batch(kb, pending_specs)
            print(
                f"[S1] 向量化 {pending_pages} 个文档 / {len(pending_specs)} 叶块（收尾）"
            )

        # 数据集统计
        stats = {
            "dataset": "chal1ce/Agricultrue_Wiki_QA_110K",
            "csv_path": str(csv_path),
            "csv_sha256": csv_sha256,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "kb": {
                "name": KB_NAME,
                "id": kb.id.hex,
                "qdrant_collection": kb.qdrant_collection,
            },
            "records": len(df),
            "pages": total_pages,
            "documents": total_docs,
            "leaf_chunks": total_chunks,
            "doc_length_chars": {
                "min": min(doc_lengths) if doc_lengths else 0,
                "max": max(doc_lengths) if doc_lengths else 0,
                "mean": round(statistics.fmean(doc_lengths), 1) if doc_lengths else 0,
                "p50": int(statistics.median(doc_lengths)) if doc_lengths else 0,
                "p90": (
                    sorted(doc_lengths)[int(len(doc_lengths) * 0.9) - 1]
                    if doc_lengths
                    else 0
                ),
            },
            "qa_per_page": {
                "min": min(qa_per_page) if qa_per_page else 0,
                "max": max(qa_per_page) if qa_per_page else 0,
                "mean": round(statistics.fmean(qa_per_page), 1) if qa_per_page else 0,
            },
        }
        save_json(CORPUS_STATS_PATH, stats)
        print(
            f"[S1] 建库完成：{total_docs} 文档 / {total_chunks} 叶块 / {total_pages} 页"
            f"（统计已写入 {CORPUS_STATS_PATH.relative_to(DATASET_ROOT)}）"
        )

        if smoke:
            await smoke_check(session, kb, df)


async def smoke_check(session, kb, df) -> None:
    """抽样验证：取首条记录的 question，确认 top-10 召回其证据 content 所在叶块。"""
    from agent.tools.document import hybrid_retrieve_multi

    pages = aggregate_by_page(df)
    first = pages[0]
    qa = first["qa_pairs"][0]
    question = qa["question"].strip()
    content = qa["content"].strip()
    if not question or not content:
        print("[S1] --smoke 跳过：首条记录 question/content 为空")
        return

    # 该页叶块（严格 gold 判定：规范化包含）
    from entity.rag.chunks import Chunk

    doc_id = await first_doc_id(session, kb, first)
    stmt = select(Chunk).where(Chunk.document_id == doc_id)
    result = await session.execute(stmt)
    gold_ids = {
        c.id.hex
        for c in result.scalars().all()
        if c.level == 0 and normalize(content) in normalize(c.content)
    }
    if not gold_ids:
        print(
            f"[S1] --smoke 警告：content 未命中任何叶块（content 可能被切块截断）: {content[:60]}"
        )
        return

    candidates = await asyncio.to_thread(hybrid_retrieve_multi, question, [kb.id], 10)
    top_ids = [cand["point_id"] for cand in candidates]
    hit = [pid for pid in top_ids if pid in gold_ids]
    rank = (top_ids.index(hit[0]) + 1) if hit else None
    if rank:
        print(
            f"[S1] --smoke PASS：question 在 top-{len(top_ids)} 召回证据叶块（rank={rank}）"
        )
    else:
        print(
            f"[S1] --smoke FAIL：未召回证据叶块。question={question[:60]}\n"
            f"      top-1 候选: {candidates[0]['text'][:80] if candidates else '(无候选)'}"
        )


async def first_doc_id(session, kb, page):
    """取某页面聚合文档的 id（宽松 gold 与 smoke 共用）。"""
    from entity.rag.document import Document

    stmt = select(Document.id).where(
        Document.knowledge_base_id == kb.id,
        Document.source_uri == f"wiki:{page['pageid']}",
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def stats_only(csv_path, limit: int | None = None) -> None:
    """仅输出数据集统计（不建库），供下载后先看数据形态。"""
    ensure_dirs()
    df = load_dataset(limit=limit)
    pages = aggregate_by_page(df)
    qa_per_page = [len(p["qa_pairs"]) for p in pages]
    doc_lengths = [len(p["text"]) for p in pages]
    stats = {
        "dataset": "chal1ce/Agricultrue_Wiki_QA_110K",
        "csv_path": str(csv_path),
        "csv_sha256": sha256_of_file(csv_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kb": None,
        "records": len(df),
        "pages": len(pages),
        "documents": 0,
        "leaf_chunks": 0,
        "doc_length_chars": {
            "min": min(doc_lengths) if doc_lengths else 0,
            "max": max(doc_lengths) if doc_lengths else 0,
            "mean": round(statistics.fmean(doc_lengths), 1) if doc_lengths else 0,
            "p50": int(statistics.median(doc_lengths)) if doc_lengths else 0,
            "p90": (
                sorted(doc_lengths)[int(len(doc_lengths) * 0.9) - 1]
                if doc_lengths
                else 0
            ),
        },
        "qa_per_page": {
            "min": min(qa_per_page) if qa_per_page else 0,
            "max": max(qa_per_page) if qa_per_page else 0,
            "mean": round(statistics.fmean(qa_per_page), 1) if qa_per_page else 0,
        },
    }
    save_json(CORPUS_STATS_PATH, stats)
    print(f"[S1] 数据集统计：{len(df)} 条记录 / {len(pages)} 页（未建库）")
    print(f"     文档长度(字符): {stats['doc_length_chars']}")
    print(f"     每页 QA 数: {stats['qa_per_page']}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="S1 评测建库（农业维基 QA 110K）")
    parser.add_argument("--csv", default=str(ensure_csv()), help="CSV 路径")
    parser.add_argument(
        "--batch", type=int, default=DEFAULT_BATCH_SIZE, help="每批向量化文档数"
    )
    parser.add_argument(
        "--force", action="store_true", help="已存在评测知识库时清理重建"
    )
    parser.add_argument(
        "--cleanup", action="store_true", help="整体删除评测知识库后退出"
    )
    parser.add_argument("--smoke", action="store_true", help="建库后抽样验证召回")
    parser.add_argument(
        "--stats-only", action="store_true", help="仅输出数据集统计（不建库）"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="仅处理前 N 条记录（子集建库）"
    )
    args = parser.parse_args()

    if args.cleanup:
        from database.postgre_client import get_session

        async with get_session() as session:
            removed = await cleanup_eval_kb(session)
        print(
            f"[S1] 已删除评测知识库 {KB_NAME}"
            if removed
            else f"[S1] 评测知识库 {KB_NAME} 不存在"
        )
        return

    if args.stats_only:
        await stats_only(args.csv, args.limit)
        return

    await build_corpus(args.csv, args.batch, args.force, args.smoke, args.limit)


if __name__ == "__main__":
    asyncio.run(main())
