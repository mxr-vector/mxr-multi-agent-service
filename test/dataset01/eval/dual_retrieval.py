"""
LongBench 双路召回评测共享设施（对齐生产管线）。

生产双路召回 = dense（embedding 工厂，Qwen3-Embedding-4B）+ sparse（jieba 中文
BM25，model/sparse/bm25.py 主路径）→ Qdrant 服务端 RRF 融合 → rerank 精排
（Qwen3-Embedding-4B，cohere 协议）。本模块提供该管线在离线评测中的
建库（专用评测知识库 + 文档摄入 + dense/sparse 向量化）与批量执行设施，
供 longbench_eval.py 复用。

与 dataset01（农业维基）评测的区别：
- gold 为文档级（数据集天然无 chunk 级证据），指标仅走 mode="doc"；
- 建库不强制两级切块：短文本单块（level=0），超长文本（> CHUNKED_MAX_LEN）
  走 ingest_file 两级切块（与生产摄取链路一致），避免 embedding 超长截断。
"""

import asyncio
import hashlib
import statistics
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Iterable, Optional, Sequence

from common import compute_metrics, mean_std, save_json

# 单块文档的文本长度上限（Qwen3-Embedding-4B max-model-len 4096 tokens，
# 中文按 1 字≈1 token 留余量）；超过则走 ingest_file 两级切块
CHUNKED_MAX_LEN = 3000
# 单次 upsert 的叶块上限。dense 2560 维 + sparse + payload 使单请求体量大，
# 且 Qdrant 偶发慢窗口（曾实测 60s 默认 HTTP 超时内无法完成），收窄到 80 点/批
# 并配显式 QDRANT_UPSERT_TIMEOUT 覆盖。
MAX_LEAVES_PER_UPSERT = 80
# 单次 embedding 请求的文本数上限（远端 vLLM 服务，控制单请求体量）
EMBED_BATCH = 40
# Qdrant upsert 请求级超时（秒）；QdrantClient 默认 60s，评测建库批量写入需更大余量
QDRANT_UPSERT_TIMEOUT = 300
# 评测查询并发上限（embedding/rerank 均为 HTTP 服务）
CONCURRENCY = 4
# 进度打印间隔
PROGRESS_EVERY = 50


def sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- 知识库管理 ---------------------------------------------------------------

async def find_kb(session, kb_name: str):
    """按名称查评测知识库（含软删除，供清理兜底）。"""
    from entity.rag.knowledge_base import KnowledgeBase
    from sqlalchemy import select

    stmt = select(KnowledgeBase).where(KnowledgeBase.name == kb_name)
    result = await session.execute(stmt)
    return result.scalars().first()


async def create_kb(session, kb_name: str, description: str) -> object:
    """创建评测知识库行（dept_id=''，id/集合名由仓储派生）。"""
    from database.rag.knowledge_base import KnowledgeBaseRepository

    repo = KnowledgeBaseRepository(session)
    return await repo.create(
        name=kb_name,
        dept_id="",
        description=description,
        visibility="private",
        owner=None,
    )


async def cleanup_kb(session, kb_name: str) -> int:
    """整体删除评测知识库：Qdrant 集合 + PG 块树 + 文档行 + 知识库行。

    块树按 document_id 分批删除（asyncpg 单语句参数上限 32767，
    评测库文档数超过该值时全量 IN 会抛 InterfaceError）。
    """
    from database.qdrant_client import QdrantManager
    from entity.rag.chunks import Chunk
    from entity.rag.document import Document
    from entity.rag.knowledge_base import KnowledgeBase
    from sqlalchemy import delete, select

    kb = await find_kb(session, kb_name)
    if kb is None:
        return 0
    await asyncio.to_thread(QdrantManager(kb.qdrant_collection).delete_collection)
    doc_ids = (
        await session.execute(
            select(Document.id).where(Document.knowledge_base_id == kb.id)
        )
    ).scalars().all()
    if doc_ids:
        batch_size = 10000
        for start in range(0, len(doc_ids), batch_size):
            batch = list(doc_ids[start : start + batch_size])
            await session.execute(
                delete(Chunk).where(Chunk.document_id.in_(batch))
            )
        await session.execute(
            delete(Document).where(Document.knowledge_base_id == kb.id)
        )
    await session.execute(delete(KnowledgeBase).where(KnowledgeBase.id == kb.id))
    await session.commit()
    return 1


def get_eval_session():
    """评测专用 async session（独立引擎，pool_pre_ping 防死连接）。

    评测建库耗时较长（embedding + Qdrant 批量写入，期间 PG 连接闲置），
    生产引擎未配置 pool_pre_ping，闲置连接被服务端关闭后继续复用会抛
    ConnectionDoesNotExistError；评测场景改用独立引擎并开启连接预检，
    不动生产连接池配置。
    """
    from core.source.postgres import PostgresConfig
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    @lru_cache(maxsize=1)
    def _factory():
        config = PostgresConfig.from_env()
        engine = create_async_engine(
            config.async_connection,
            pool_pre_ping=True,
            pool_recycle=600,
        )
        return async_sessionmaker(bind=engine, expire_on_commit=False)

    return _factory()()


# ---- 文档摄入 ---------------------------------------------------------------

async def _bulk_insert_chunks(session, chunks) -> None:
    from database.rag.chunks import ChunkRepository

    await ChunkRepository(session).bulk_insert(chunks)


def _leaf_specs_from_chunks(kb, doc, leaf_chunks) -> list[dict]:
    """叶块 → 向量化 specs（payload 与生产 vectorize_job 对齐 + source_uri/title）。"""
    specs = []
    for leaf in leaf_chunks:
        specs.append(
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
                    "source_uri": doc.source_uri,
                    "title": doc.title,
                },
                "id": leaf.id.hex,
            }
        )
    return specs


async def ingest_document(
    session,
    kb,
    title: str,
    text: str,
    source_uri: str,
    source_system: str,
    metadata: Optional[dict] = None,
    chunked_max_len: int = CHUNKED_MAX_LEN,
) -> tuple[Optional[object], list[dict]]:
    """摄入单个文档：短文本单块，超长文本 ingest_file 两级切块。

    返回 (doc, leaf_specs)；text 为空返回 (None, [])。doc 行与块树由调用方提交。
    """
    from database.rag.document import DocumentRepository
    from entity.rag.chunks import Chunk

    text = text.strip()
    if not text:
        return None, []
    doc_repo = DocumentRepository(session)
    doc = await doc_repo.create(
        knowledge_base_id=kb.id,
        content=text,
        content_hash=sha256_of_text(text),
        doc_type="text",
        source_uri=source_uri,
        source_system=source_system,
        title=title,
        metadata=metadata or {},
        status="active",
        dept_id="",
    )

    if len(text) <= chunked_max_len:
        # 单块文档：整段为唯一叶块（无父块）
        leaf = Chunk(
            document_id=doc.id,
            document_version=doc.version,
            level=0,
            chunk_index=0,
            content=text,
            parent_chunk_id=None,
            char_start=0,
            char_end=len(text),
            chapter_title=None,
            page_start=None,
            page_end=None,
            content_hash=sha256_of_text(text),
            chunk_metadata={},
            dept_id="",
        )
        await _bulk_insert_chunks(session, [leaf])
        return doc, _leaf_specs_from_chunks(kb, doc, [leaf])

    # 超长文本：两级切块（与生产摄取链路一致）
    from utils.file_ingest import ingest_file

    parsed = ingest_file(f"{title}.txt", text.encode("utf-8"))
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
    await _bulk_insert_chunks(session, leaf_chunks)
    return doc, _leaf_specs_from_chunks(kb, doc, leaf_chunks)


async def _embed_with_retry(texts: list[str], attempts: int = 6) -> list[list[float]]:
    """dense 向量化带退避重试（远端 vLLM 偶发连接重置/超时，同 Qdrant 写入策略）。

    embedding 客户端自身的 max_retries 很小（ENV.embedding_max_retries=1，
    避免生产作业卡死）；评测建库批量大、耗时长，这里额外兜底重试，
    连接瞬时抖动时不会整体崩溃。
    """
    from model.embeddings.factory import get_embedding_client

    client = get_embedding_client()
    for attempt in range(1, attempts + 1):
        try:
            return client.embed_documents(texts)
        except Exception as exc:
            if attempt == attempts:
                raise
            delay = 5.0 * attempt
            print(
                f"[eval] dense 向量化失败({type(exc).__name__})，"
                f"{delay:.0f}s 后重试 {attempt}/{attempts}",
                flush=True,
            )
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")


async def vectorize_batch(kb, leaf_specs: list[dict]) -> None:
    """一批叶块写入 Qdrant（dense+sparse，同步 IO 丢线程池）。

    不直接复用生产 upsert_hybrid：评测建库批量大，需要请求级 timeout 覆盖
    Qdrant 偶发慢窗口，并分批控制 embedding 请求体量。向量计算与 payload 与
    生产一致（embedding 工厂 + bm25 主路径 + 同名命名向量）。
    """
    from database.qdrant_client import (
        DENSE_VECTOR_NAME,
        QdrantManager,
        SPARSE_VECTOR_NAME,
    )
    from model.sparse.bm25 import embed_documents as sparse_embed_documents
    from qdrant_client.models import PointStruct

    manager = QdrantManager(kb.qdrant_collection)
    for start in range(0, len(leaf_specs), MAX_LEAVES_PER_UPSERT):
        batch = leaf_specs[start : start + MAX_LEAVES_PER_UPSERT]
        texts = [spec["text"] for spec in batch]

        dense_vectors: list[list[float]] = []
        for estart in range(0, len(texts), EMBED_BATCH):
            dense_vectors.extend(
                await _embed_with_retry(texts[estart : estart + EMBED_BATCH])
            )
        sparse_vectors = sparse_embed_documents(texts)

        points = [
            PointStruct(
                id=spec["id"],
                vector={
                    DENSE_VECTOR_NAME: list(dv),
                    SPARSE_VECTOR_NAME: sv,
                },
                payload={**spec["payload"], "text": spec["text"]},
            )
            for spec, dv, sv in zip(batch, dense_vectors, sparse_vectors)
        ]
        await _write_with_retry(manager, points, len(dense_vectors[0]))


async def _write_with_retry(
    manager, points: list, dense_size: int, attempts: int = 6
) -> None:
    """ensure 集合 + Qdrant upsert 带退避重试（点按 id 幂等，重复写入安全）。

    Qdrant 服务端偶发慢窗口/连接中断（实测 ConnectTimeout/ReadTimeout，
    collection_exists 与 upsert 均可能触发），整体重试确保批次最终落库；
    超时后服务端仍可能继续完成写入，重试按 point id 覆盖，不产生重复点。
    """
    for attempt in range(1, attempts + 1):
        try:
            manager.ensure_hybrid_collection(dense_size)
            await asyncio.to_thread(
                manager.client.upsert,
                collection_name=manager.collection,
                points=points,
                timeout=QDRANT_UPSERT_TIMEOUT,
            )
            return
        except Exception as exc:
            if attempt == attempts:
                raise
            delay = 5.0 * attempt
            print(
                f"[eval] 写入 {len(points)} 点失败({type(exc).__name__})，"
                f"{delay:.0f}s 后重试 {attempt}/{attempts}",
                flush=True,
            )
            await asyncio.sleep(delay)


async def ingest_document_retry(
    session_factory,
    kb,
    title: str,
    text: str,
    source_uri: str,
    source_system: str,
    metadata: Optional[dict] = None,
    attempts: int = 3,
) -> tuple[Optional[object], list[dict]]:
    """ingest_document + commit，DB 异常时开新 session 重试（评测专用）。

    评测目标机（PG/Qdrant 同机）实测存在服务端中途关闭连接（
    ConnectionDoesNotExistError）的间歇故障；事务回滚后重试安全，
    用独立 session 工厂重开会话规避死连接复用。
    """
    from sqlalchemy.exc import DBAPIError

    for attempt in range(1, attempts + 1):
        try:
            async with session_factory() as session:
                ingested, leaf_specs = await ingest_document(
                    session,
                    kb,
                    title=title,
                    text=text,
                    source_uri=source_uri,
                    source_system=source_system,
                    metadata=metadata,
                )
                await session.commit()
                return ingested, leaf_specs
        except DBAPIError as exc:
            if attempt == attempts:
                raise
            delay = 5 * attempt
            print(
                f"[eval] DB 写入失败({type(exc).__name__})，"
                f"{delay}s 后重试 {attempt}/{attempts}",
                flush=True,
            )
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")


# ---- 评测执行 ---------------------------------------------------------------

async def rerank_candidates(query: str, candidates: list[dict]) -> list[dict]:
    """rerank 精排候选池（生产 rerank 角色，Qwen3-Embedding-4B cohere 协议）。"""
    if not candidates:
        return candidates
    from model.rerank.factory import get_rerank_client

    client = get_rerank_client()
    texts = [c["text"] for c in candidates]
    results = await asyncio.to_thread(client.rerank, query, texts, top_n=len(texts))
    reordered = []
    for r in results:
        cand = candidates[r.index]
        cand["score"] = r.score
        reordered.append(cand)
    return reordered


async def run_eval(
    queries: list[dict],
    kb,
    pool_size: int,
    use_rerank: bool = True,
    concurrency: int = CONCURRENCY,
) -> list[dict]:
    """批量执行双路召回评测（hybrid_retrieve_multi + 可选 rerank）。

    queries: [{qid, question, gold_docs: [doc_id_hex, ...]}]；
    返回 [{qid, question, gold_docs, status, candidates, latency_ms, error}]，
    candidates 含 point_id/document_id/score/text（rerank 后 score 为精排得分）。
    """
    from agent.tools.document import hybrid_retrieve_multi

    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(item: dict) -> dict:
        async with semaphore:
            question = (item.get("question") or "").strip()
            out: dict = {
                "qid": item["qid"],
                "question": question,
                "gold_docs": item.get("gold_docs") or [],
                "status": "ok",
                "candidates": [],
                "latency_ms": 0,
            }
            started = time.monotonic()
            try:
                candidates = await asyncio.to_thread(
                    hybrid_retrieve_multi, question, [kb.id], pool_size
                )
                if use_rerank:
                    candidates = await rerank_candidates(question, candidates)
                out["candidates"] = [
                    {
                        "point_id": cand["point_id"],
                        "document_id": cand.get("document_id"),
                        "score": cand.get("score"),
                        "text": cand.get("text", ""),
                    }
                    for cand in candidates
                ]
                out["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
            except Exception as exc:
                out["status"] = "failed"
                out["error"] = str(exc)[:300]
            return out

    results: list[dict] = []
    done = 0
    started_all = time.monotonic()
    for coro in asyncio.as_completed([run_one(item) for item in queries]):
        results.append(await coro)
        done += 1
        if done % PROGRESS_EVERY == 0 or done == len(queries):
            elapsed = time.monotonic() - started_all
            print(f"[eval] 进度 {done}/{len(queries)}（耗时 {elapsed:.0f}s）", flush=True)
    failed = sum(1 for r in results if r["status"] == "failed")
    print(f"[eval] 完成：{len(results)} 条（失败 {failed}，rerank={'on' if use_rerank else 'off'}）")
    return results


# ---- 指标汇总 ---------------------------------------------------------------

def summarize(results: list[dict], ks: Sequence[int]) -> dict:
    """文档级口径（mode='doc'）宏平均 Recall@K / Precision@K / NDCG@K / MRR。

    返回 {metrics: {k: {recall: [mean,std], precision: [mean,std],
                          ndcg: [mean,std]}, mrr: [mean,std]},
          valid, failed, empty_gold}；gold 为空的 query 不计入指标（单列统计）。
    """
    acc: dict = {
        "recall": {int(k): [] for k in ks},
        "precision": {int(k): [] for k in ks},
        "ndcg": {int(k): [] for k in ks},
        "mrr": [],
    }
    counts = {"valid": 0, "failed": 0, "empty_gold": 0}
    for item in results:
        if item["status"] != "ok":
            counts["failed"] += 1
            continue
        gold = [g for g in (item.get("gold_docs") or []) if g]
        if not gold:
            counts["empty_gold"] += 1
            continue
        metrics = compute_metrics(item["candidates"], gold, ks, mode="doc")
        if metrics is None:
            counts["empty_gold"] += 1
            continue
        counts["valid"] += 1
        acc["mrr"].append(metrics["mrr"])
        for k in ks:
            k = int(k)
            acc["recall"][k].append(metrics[k]["recall"])
            acc["precision"][k].append(metrics[k]["precision"])
            acc["ndcg"][k].append(metrics[k]["ndcg"])
    out: dict = {"metrics": {}, "counts": counts}
    for k in ks:
        k = int(k)
        out["metrics"][k] = {
            "recall": mean_std(acc["recall"][k]),
            "precision": mean_std(acc["precision"][k]),
            "ndcg": mean_std(acc["ndcg"][k]),
        }
    out["metrics"]["mrr"] = mean_std(acc["mrr"])
    return out


def fmt_ms(value: tuple[float, float] | None) -> str:
    """指标单元格格式：mean±std 或 '—'（无有效样本）。"""
    if value is None:
        return "—"
    return f"{value[0]:.3f}±{value[1]:.3f}"


def report_lines(
    title: str,
    meta: dict,
    summary: dict,
    ks: Sequence[int],
    extra: Optional[list[str]] = None,
) -> list[str]:
    """标准 Markdown 报告文本（双路召回 + rerank 单管线、文档级口径）。"""
    counts = summary["counts"]
    metrics = summary["metrics"]
    lines: list[str] = [
        f"# {title}",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        f"- 评测知识库：{meta.get('kb_id')}（candidate_pool={meta.get('pool_size')}，"
        f"rerank={'on' if meta.get('rerank') else 'off'}）",
        f"- 执行 query：{counts['valid'] + counts['empty_gold'] + counts['failed']} 条"
        f"（有效 {counts['valid']} / gold 为空 {counts['empty_gold']} / 失败 {counts['failed']}）",
    ]
    for key, value in meta.items():
        if key not in ("kb_id", "pool_size", "rerank", "created_at"):
            lines.append(f"- {key}：{value}")
    lines.extend(["", "## 文档级指标（gold = qrels/可辩护证据 → document_id，mode=doc）", ""])
    lines.append("| K | Recall@K | Precision@K | NDCG@K |")
    lines.append("|---|---|---|---|")
    for k in ks:
        k = int(k)
        lines.append(
            f"| {k} | {fmt_ms(metrics[k]['recall'])} | {fmt_ms(metrics[k]['precision'])} | {fmt_ms(metrics[k]['ndcg'])} |"
        )
    lines.append(f"| MRR | {fmt_ms(metrics['mrr'])} | — | — |")
    lines.extend(["", f"有效 query 数：{counts['valid']}"])
    if extra:
        lines.extend(["", *extra])
    return lines
