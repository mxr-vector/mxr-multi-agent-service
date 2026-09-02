"""
S3 双管线查询执行：对抽样 query 逐条执行纯检索（A）与完整工具管线（B），落盘明细。

- A 纯检索：hybrid_retrieve_multi（dense+sparse RRF，候选池排序，无反思无重排）
- B 完整工具管线：agent.tools.rag_tools.knowledge_base_search_impl
  （混合召回 + 反思自纠错改写重检 + rerank 后 top-k）
- 限流并发 4（embedding/rewrite/rerank 均为 HTTP 服务）；单条失败标记 failed 继续
- 产物缓存：results/eval_results.json 的 meta 与当前配置一致时直接复用（--force 重跑）

用法：
  uv run python test/dataset01/eval/run_queries.py [--max-queries N] [--no-graph] [--force]
"""

import argparse
import asyncio
import re
import time
import uuid
from datetime import datetime, timezone

from common import (
    CORPUS_STATS_PATH,
    DEFAULT_SAMPLE_SIZE,
    DEFAULT_SEED,
    EVAL_RESULTS_PATH,
    GOLD_RELAXED_PATH,
    GOLD_STRICT_PATH,
    SAMPLE_QUERIES_PATH,
    ensure_cfg_async,
    ensure_dirs,
    load_json,
    save_json,
)

# 查询并发上限（embedding/rewrite/rerank 均为 HTTP 服务，避免打爆）
CONCURRENCY = 4
# 进度打印间隔
PROGRESS_EVERY = 50
# 单条 B 管线（工具含多轮外部 LLM 调用）超时兜底：外部 API 偶发挂起时
# 标记 failed 继续，避免单条拖死全量评测（正常 1 轮反思约 6s，3 轮上限远低于此）
PIPELINE_B_TIMEOUT = 180


def _meta_for(
    kb_id_hex: str,
    stats: dict,
    seed: int,
    sample_size: int,
    no_graph: bool,
    pool_size: int,
    split_query: bool,
    rerank: bool,
    sparse_encoder: str = "default",
) -> dict:
    """评测元数据（缓存校验键）：数据集/知识库/抽样/系统配置均参与比对。"""
    from core.config_snapshot import CFG

    return {
        "kb_id": kb_id_hex,
        "dataset_sha256": stats.get("csv_sha256", ""),
        "seed": seed,
        "sample_size": sample_size,
        "candidate_pool_size": pool_size,
        "final_top_k": CFG.rag_final_top_k,
        "reflect_round_cap": CFG.rag_reflect_round_cap,
        "no_graph": no_graph,
        "split_query": split_query,
        "rerank": rerank,
        "sparse_encoder": sparse_encoder,
    }


def split_sub_queries(question: str, min_len: int = 5) -> list[str]:
    """把拼接式 question（3~4 个问题用问号连接）拆分为子问题列表。"""
    parts = [p.strip() for p in re.split(r"[？?。；;\n]+", question)]
    return [p for p in parts if len(p) >= min_len]


async def run_pipeline_a(
    query: str,
    kb_id: uuid.UUID,
    pool_size: int,
    split_query: bool = False,
    rerank: bool = False,
    sparse_encoder: str = "default",
) -> dict:
    """纯检索管线：混合召回候选池（同步 IO 丢线程池），记录排序与得分。

    split_query=True 时把拼接式 query 拆为子问题多路检索，按轮转合并去重
    （模拟"多路检索"策略，不改生产代码的评测侧实验）。
    sparse_encoder="jieba" 时使用 jieba 中文 BM25 词法通道（需评测库已重算
    sparse 向量），验证中文词法召回增益。
    """
    from agent.tools.document import hybrid_retrieve, hybrid_retrieve_multi

    if sparse_encoder == "jieba":
        # 自定义 sparse 向量注入单库检索（dense 走标准 embedding）
        from model.embeddings.factory import get_embedding_client
        from model.sparse.bm25_jieba import embed_query as jieba_sparse_embed

        dense_vector = await asyncio.to_thread(
            get_embedding_client().embed_query, query
        )
        sparse_vector = await asyncio.to_thread(jieba_sparse_embed, query)
        candidates = await asyncio.to_thread(
            hybrid_retrieve, query, kb_id, pool_size, dense_vector, sparse_vector
        )
    elif split_query:
        subs = split_sub_queries(query)
        if len(subs) > 1:
            # 每个子问题保持完整池大小检索（不缩小召回空间），合并去重后截断
            batches = []
            for sub in subs:
                candidates = await asyncio.to_thread(
                    hybrid_retrieve_multi, sub, [kb_id], pool_size
                )
                batches.append(candidates)
            # 轮转合并去重：各子问题候选交替进入最终池
            merged: list[dict] = []
            seen: set = set()
            for round_idx in range(max(len(b) for b in batches)):
                for batch in batches:
                    if round_idx < len(batch):
                        cand = batch[round_idx]
                        pid = cand["point_id"]
                        if pid not in seen:
                            seen.add(pid)
                            merged.append(cand)
                if len(merged) >= pool_size:
                    break
            candidates = merged[:pool_size]
        else:
            candidates = await asyncio.to_thread(
                hybrid_retrieve_multi, query, [kb_id], pool_size
            )
    else:
        candidates = await asyncio.to_thread(
            hybrid_retrieve_multi, query, [kb_id], pool_size
        )
    if rerank:
        candidates = await rerank_candidates(query, candidates)
    return {
        "status": "ok",
        "candidates": [
            {
                "point_id": cand["point_id"],
                "document_id": cand.get("document_id"),
                "score": cand.get("score"),
                "text": cand.get("text", ""),
            }
            for cand in candidates
        ],
    }


async def rerank_candidates(query: str, candidates: list[dict]) -> list[dict]:
    """本地 rerank 重排候选池（Qwen3-Embedding-4B，cohere 协议，零云端 token）。

    模拟生产"检索 → 重排"精简链路（不含云端 rewrite），用于验证
    池内有 gold 但排序不到位场景的增益。
    """
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


async def run_pipeline_b(query: str, kb_id_hex: str) -> dict:
    """完整工具管线：反思自纠错 + 重排序，输出 reranked docs 与检索指标。

    与生产 respond 节点共用 agent.tools.rag_tools.knowledge_base_search_impl
    （不经过对话模型，仅验证检索链路本身）。
    """
    from agent.tools.rag_tools import knowledge_base_search_impl

    outcome = await asyncio.wait_for(
        knowledge_base_search_impl(query, [kb_id_hex]),
        timeout=PIPELINE_B_TIMEOUT,
    )
    metrics = outcome.metrics or {}
    return {
        "status": "ok",
        "reranked": [
            {
                "point_id": doc.get("point_id"),
                "document_id": doc.get("document_id"),
                "score": doc.get("score"),
                "text": doc.get("text", ""),
            }
            for doc in outcome.docs
        ],
        "metrics": {
            "reflect_rounds": metrics.get("reflect_rounds", 0),
            "retrieved_count": metrics.get("retrieved_count", 0),
            "reranked_count": metrics.get("reranked_count", 0),
        },
    }


async def run_one(
    semaphore: asyncio.Semaphore,
    item: dict,
    strict_gold: dict,
    relaxed_gold: dict,
    kb_id: uuid.UUID,
    pool_size: int,
    no_graph: bool,
    split_query: bool,
    rerank: bool,
    sparse_encoder: str,
) -> dict:
    """单条 query 双管线执行（协程内 A→B 串行，协程间受信号量限流）。"""
    row_index = str(item["row_index"])
    question = (item.get("question") or "").strip()
    async with semaphore:
        out: dict = {
            "row_index": row_index,
            "question": question,
            "strict_gold": strict_gold.get(row_index, []),
            "relaxed_gold": relaxed_gold.get(row_index, []),
            "pipeline_a": {"status": "skipped", "candidates": []},
            "pipeline_b": {"status": "skipped", "reranked": [], "metrics": {}},
        }
        try:
            out["pipeline_a"] = await run_pipeline_a(
                question, kb_id, pool_size, split_query, rerank, sparse_encoder
            )
        except Exception as exc:
            out["pipeline_a"] = {
                "status": "failed",
                "candidates": [],
                "error": str(exc)[:300],
            }
        if not no_graph:
            try:
                out["pipeline_b"] = await run_pipeline_b(question, kb_id.hex)
            except Exception as exc:
                out["pipeline_b"] = {
                    "status": "failed",
                    "reranked": [],
                    "metrics": {},
                    "error": str(exc)[:300],
                }
        return out


async def run_queries(
    max_queries: int | None,
    no_graph: bool,
    force: bool,
    pool_size: int | None = None,
    split_query: bool = False,
    rerank: bool = False,
    sparse_encoder: str = "default",
) -> None:
    await ensure_cfg_async()
    ensure_dirs()

    sample = load_json(SAMPLE_QUERIES_PATH)
    stats = load_json(CORPUS_STATS_PATH)
    strict_gold = load_json_strict()
    relaxed_gold = load_json_relaxed()

    from database.postgre_client import get_session

    from build_corpus import find_eval_kb

    async with get_session() as session:
        kb = await find_eval_kb(session)
        if kb is None:
            raise SystemExit("评测知识库不存在：请先运行 build_corpus.py 建库")

    seed = sample["meta"].get("seed", DEFAULT_SEED)
    sample_size = len(sample["queries"])
    from core.config_snapshot import CFG

    pool_size = pool_size or CFG.rag_candidate_pool_size
    meta = _meta_for(
        kb.id.hex,
        stats,
        seed,
        sample_size,
        no_graph,
        pool_size,
        split_query,
        rerank,
        sparse_encoder,
    )

    # 缓存复用：meta 一致且非 --force → 直接复用已有明细
    if not force and EVAL_RESULTS_PATH.exists():
        existing = load_json(EVAL_RESULTS_PATH)
        if existing.get("meta") == meta:
            print(
                f"[S3] 命中产物缓存：{EVAL_RESULTS_PATH}（meta 一致，复用 {len(existing['results'])} 条）"
            )
            print("     强制重跑请加 --force")
            return

    queries = sample["queries"][:max_queries] if max_queries else sample["queries"]
    print(
        f"[S3] 开始执行 {len(queries)} 条 query（并发 {CONCURRENCY}，"
        f"candidate_pool={meta['candidate_pool_size']}, final_top_k={meta['final_top_k']}）"
    )

    semaphore = asyncio.Semaphore(CONCURRENCY)
    started = time.monotonic()
    # 并发执行（run_one 内部以信号量限流；按完成顺序收集，进度按完成数打印）
    done = 0
    results: list[dict] = []
    for coro in asyncio.as_completed(
        [
            run_one(
                semaphore,
                item,
                strict_gold,
                relaxed_gold,
                kb.id,
                meta["candidate_pool_size"],
                no_graph,
                split_query,
                rerank,
                sparse_encoder,
            )
            for item in queries
        ]
    ):
        results.append(await coro)
        done += 1
        if done % PROGRESS_EVERY == 0 or done == len(queries):
            elapsed = time.monotonic() - started
            print(f"[S3] 进度 {done}/{len(queries)}（耗时 {elapsed:.0f}s）", flush=True)

    failed_a = sum(1 for r in results if r["pipeline_a"]["status"] == "failed")
    failed_b = sum(
        1 for r in results if not no_graph and r["pipeline_b"]["status"] == "failed"
    )
    payload = {
        "meta": {**meta, "created_at": datetime.now(timezone.utc).isoformat()},
        "results": results,
    }
    save_json(EVAL_RESULTS_PATH, payload)
    print(
        f"[S3] 完成：{len(results)} 条（A 失败 {failed_a}，B 失败 {failed_b}），"
        f"已落盘 {EVAL_RESULTS_PATH}"
    )


def load_json_strict() -> dict:
    """严格口径 gold：{row_index: [chunk_id, ...]}。"""
    return load_json(GOLD_STRICT_PATH)["gold"]


def load_json_relaxed() -> dict:
    """宽松口径 gold：{row_index: [doc_id, ...]}。"""
    return load_json(GOLD_RELAXED_PATH)["gold"]


async def main() -> None:
    parser = argparse.ArgumentParser(description="S3 双管线查询执行")
    parser.add_argument(
        "--max-queries", type=int, default=None, help="仅执行前 N 条（冒烟）"
    )
    parser.add_argument(
        "--no-graph", action="store_true", help="跳过完整子图管线（仅纯检索）"
    )
    parser.add_argument("--force", action="store_true", help="忽略缓存强制重跑")
    parser.add_argument(
        "--pool",
        type=int,
        default=None,
        help="候选池大小（默认取系统 RAG_CANDIDATE_POOL_SIZE）",
    )
    parser.add_argument(
        "--split-query",
        action="store_true",
        help="拼接式 query 拆分为子问题多路检索（评测实验）",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="A 管线候选池追加本地 rerank 重排（检索→重排精简链路）",
    )
    parser.add_argument(
        "--sparse-encoder",
        choices=["default", "jieba"],
        default="default",
        help="sparse 词法编码器（jieba=中文 BM25，需评测库已重算 sparse 向量）",
    )
    args = parser.parse_args()
    await run_queries(
        args.max_queries,
        args.no_graph,
        args.force,
        args.pool,
        args.split_query,
        args.rerank,
        args.sparse_encoder,
    )


if __name__ == "__main__":
    asyncio.run(main())
