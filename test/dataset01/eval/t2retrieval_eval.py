"""
C-MTEB/T2Retrieval 双路召回评测适配器（受限语料，对齐生产管线）。

- 语料：corpus 前 1000 条文档（--max-corpus 可调）建独立评测知识库；
  评测 query = qrels 中 gold 文档全部落在库内的 test query 全量（可评测口径）。
- 管线：hybrid_retrieve_multi（dense + jieba BM25 RRF，candidate_pool=50）
  + rerank 精排（Qwen3-Embedding-4B cohere 协议），与生产配置一致。
- 指标：Recall@K / Precision@K / MRR（K∈{1,3,5,10}，文档级，宏平均±std）。
- 产物：
  - gold/t2retrieval_doc_map.json：t2 id → PG 文档 id 映射（建库指纹）
  - results/t2retrieval_dual_results.json：逐 query 明细
  - results/t2retrieval_dual_summary.json：汇总指标

数据来源（HF）：C-MTEB/T2Retrieval（corpus/queries parquet）+ C-MTEB/T2Retrieval-qrels。
下载脚本见 test/dataset01/README.md；已下载文件位于 test/dataset01/data/。

用法：
  uv run python test/dataset01/eval/t2retrieval_eval.py [--force] [--cleanup]
      [--max-corpus 1000] [--max-queries N] [--no-rerank] [--pool 50]
"""

import argparse
import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path

from common import BASE_K_VALUES, DATA_DIR, GOLD_DIR, RESULTS_DIR, ensure_cfg_async, load_json, save_json

from dual_retrieval import (
    cleanup_kb,
    create_kb,
    find_kb,
    get_eval_session,
    ingest_document,
    report_lines,
    run_eval,
    summarize,
    vectorize_batch,
)

KB_NAME = "dataset01-t2retrieval"
KB_DESCRIPTION = "RAG 双路召回评测语料库：C-MTEB/T2Retrieval（corpus 前 1000 文档受限口径）"

CORPUS_PATH = DATA_DIR / "t2_corpus.parquet"
QUERIES_PATH = DATA_DIR / "t2_queries.parquet"
QRELS_PATH = DATA_DIR / "t2_qrels_dev.parquet"
DOC_MAP_PATH = GOLD_DIR / "t2retrieval_doc_map.json"
RESULTS_PATH = RESULTS_DIR / "t2retrieval_dual_results.json"
SUMMARY_PATH = RESULTS_DIR / "t2retrieval_dual_summary.json"

# 默认受限语料规模（corpus 前 N 条文档）
DEFAULT_MAX_CORPUS = 1000


def _require_data() -> None:
    missing = [p for p in (CORPUS_PATH, QUERIES_PATH, QRELS_PATH) if not p.exists()]
    if missing:
        raise SystemExit(
            f"缺少数据文件: {[str(p) for p in missing]}\n"
            "请从 HF 下载（HF_ENDPOINT=https://hf-mirror.com）：\n"
            "  C-MTEB/T2Retrieval: data/corpus-*.parquet, data/queries-*.parquet\n"
            "  C-MTEB/T2Retrieval-qrels: data/dev-*.parquet\n"
            "并重命名为 t2_corpus.parquet / t2_queries.parquet / t2_qrels_dev.parquet"
        )


def clean_text(text: str) -> str:
    """轻量清洗网页残留：<br> 转换行，其余 HTML 标签剔除。"""
    text = re.sub(r"<br\s*/?>", "\n", text)
    return re.sub(r"<[^>]+>", "", text)


def load_dataset(max_corpus: int) -> tuple[list[dict], dict]:
    """读 parquet：corpus 前 max_corpus 条（清洗后）+ queries/qrels 映射。"""
    import pandas as pd

    corpus = pd.read_parquet(CORPUS_PATH)
    queries = pd.read_parquet(QUERIES_PATH)
    qrels = pd.read_parquet(QRELS_PATH)
    docs = [
        {"id": str(row.id), "text": clean_text(str(row.text))}
        for row in corpus.head(max_corpus).itertuples()
    ]
    qtext = {str(r.id): str(r.text) for r in queries.itertuples()}
    gold_by_q: dict[str, set] = {}
    for r in qrels.itertuples():
        qid, pid = str(r.qid), str(r.pid)
        if int(r.score) > 0:
            gold_by_q.setdefault(qid, set()).add(pid)
    return docs, {"queries": qtext, "gold_by_q": gold_by_q}


async def build(session, docs: list[dict], force: bool, batch_size: int = 50) -> object:
    """建库（幂等：KB 与 doc map 指纹一致时复用；--force 重建）。"""
    import hashlib

    from common import load_json

    # 建库指纹：corpus 内容 + 语料规模（doc map 缓存复用依据）
    fp = hashlib.sha256(
        ("\n".join(d["id"] + d["text"][:200] for d in docs)).encode("utf-8")
    ).hexdigest()[:16]

    existing = await find_kb(session, KB_NAME)
    if existing is not None and not force:
        if DOC_MAP_PATH.exists():
            cached = load_json(DOC_MAP_PATH)
            if cached.get("fingerprint") == fp:
                print(
                    f"[t2] 评测知识库已存在且指纹一致: {KB_NAME} id={existing.id.hex}"
                    f"（复用 {len(cached['mapping'])} 个文档映射，重建请加 --force）"
                )
                return existing, cached["mapping"]
        print(
            f"[t2] 评测知识库已存在但指纹不一致（重建请加 --force），"
            f"继续使用既有库: {existing.id.hex}"
        )
        return existing, {}

    if existing is not None and force:
        print(f"[t2] --force：清理既有评测知识库 {KB_NAME}...")
        await cleanup_kb(session, KB_NAME)

    kb = await create_kb(session, KB_NAME, KB_DESCRIPTION)
    await session.commit()
    print(f"[t2] 已创建评测知识库: {KB_NAME} id={kb.id.hex} collection={kb.qdrant_collection}")

    mapping: dict[str, str] = {}
    total_leaves = 0
    pending_specs: list[dict] = []
    for idx, doc in enumerate(docs, start=1):
        ingested, leaf_specs = await ingest_document(
            session,
            kb,
            title=f"t2:{doc['id']}",
            text=doc["text"],
            source_uri=f"t2:{doc['id']}",
            source_system="C-MTEB-T2Retrieval",
            metadata={"t2_id": doc["id"]},
        )
        if ingested is None:
            continue
        await session.commit()
        mapping[doc["id"]] = ingested.id.hex
        total_leaves += len(leaf_specs)
        pending_specs.extend(leaf_specs)
        if idx % batch_size == 0:
            await vectorize_batch(kb, pending_specs)
            print(f"[t2] 向量化 {idx}/{len(docs)} 文档（累计叶块 {total_leaves}）")
            pending_specs = []
    if pending_specs:
        await vectorize_batch(kb, pending_specs)
        print(f"[t2] 向量化收尾（累计叶块 {total_leaves}）")

    save_json(
        DOC_MAP_PATH,
        {
            "dataset": "C-MTEB/T2Retrieval",
            "fingerprint": fp,
            "max_corpus": len(docs),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "kb_id": kb.id.hex,
            "mapping": mapping,
        },
    )
    print(f"[t2] 建库完成：{len(mapping)} 文档 / {total_leaves} 叶块")
    return kb, mapping


def select_queries(docs: list[dict], dataset: dict) -> list[dict]:
    """筛选可评测 query：qrels gold 非空且全部落在库内文档集合中。"""
    in_kb = {d["id"] for d in docs}
    queries = []
    for qid, gold in dataset["gold_by_q"].items():
        if not gold or not gold <= in_kb:
            continue
        question = dataset["queries"].get(qid)
        if not question:
            continue
        queries.append({"qid": qid, "question": question, "gold_docs": sorted(gold)})
    queries.sort(key=lambda q: int(q["qid"]) if q["qid"].isdigit() else q["qid"])
    return queries


async def main() -> None:
    parser = argparse.ArgumentParser(description="T2Retrieval 双路召回评测（受限语料）")
    parser.add_argument("--force", action="store_true", help="已存在评测知识库时清理重建")
    parser.add_argument("--cleanup", action="store_true", help="整体删除评测知识库后退出")
    parser.add_argument("--max-corpus", type=int, default=DEFAULT_MAX_CORPUS, help="corpus 前 N 条文档建库")
    parser.add_argument("--max-queries", type=int, default=None, help="仅评测前 N 条 query（冒烟）")
    parser.add_argument("--retry-failed", action="store_true", help="仅补跑上次失败（status!=ok）的 query 并合并结果")
    parser.add_argument("--no-rerank", action="store_true", help="跳过 rerank（仅双路召回检索层）")
    parser.add_argument("--pool", type=int, default=None, help="候选池大小（默认取系统 RAG_CANDIDATE_POOL_SIZE）")
    args = parser.parse_args()

    await ensure_cfg_async()
    from core.config_snapshot import CFG

    _require_data()
    pool_size = args.pool or CFG.rag_candidate_pool_size

    if args.cleanup:
        async with get_eval_session() as session:
            removed = await cleanup_kb(session, KB_NAME)
        print(f"[t2] 已删除评测知识库 {KB_NAME}" if removed else f"[t2] 评测知识库 {KB_NAME} 不存在")
        return

    docs, dataset = load_dataset(args.max_corpus)
    print(f"[t2] 数据就绪：corpus 前 {len(docs)} 文档 / qrels {len(dataset['gold_by_q'])} query")

    async with get_eval_session() as session:
        kb, mapping = await build(session, docs, args.force)
        if not mapping:
            # 复用既有库时 mapping 缺失：从 PG 文档重建映射（source_uri=t2:*）
            from sqlalchemy import select

            from entity.rag.document import Document

            rows = (
                await session.execute(
                    select(Document.id, Document.source_uri).where(
                        Document.knowledge_base_id == kb.id
                    )
                )
            ).all()
            mapping = {r.source_uri.removeprefix("t2:"): r.id.hex for r in rows}
            print(f"[t2] 从 PG 重建文档映射：{len(mapping)} 个")

    queries = select_queries(docs, dataset)
    # gold 映射为 PG 文档 id（库内 id 一定在 mapping 中）
    for q in queries:
        q["gold_docs"] = [mapping[gid] for gid in q["gold_docs"]]
    if args.max_queries:
        queries = queries[: args.max_queries]
    print(f"[t2] 可评测 query：{len(queries)} 条（gold 全部落在库内，seed 无关确定性筛选）")

    if args.retry_failed:
        if not RESULTS_PATH.exists():
            raise SystemExit(f"--retry-failed 需要已有结果文件: {RESULTS_PATH}")
        prev = load_json(RESULTS_PATH)
        failed_qids = {r["qid"] for r in prev["results"] if r["status"] != "ok"}
        if not failed_qids:
            print("[t2] 无失败 query，无需补跑")
            return
        retry = [q for q in queries if q["qid"] in failed_qids]
        print(f"[t2] 补跑失败 query：{len(retry)} 条（{sorted(failed_qids)}）")
        fresh = await run_eval(retry, kb, pool_size, use_rerank=not args.no_rerank)
        by_qid = {r["qid"]: r for r in fresh}
        merged = [by_qid.get(r["qid"], r) for r in prev["results"]]
        results = merged
        payload = {
            **prev,
            "results": results,
            "meta": {
                **prev["meta"],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "retried_failed": len(retry),
            },
        }
        print(f"[t2] 合并后结果：{len(results)} 条（失败 {sum(1 for r in results if r['status'] != 'ok')}）")
    else:
        results = await run_eval(queries, kb, pool_size, use_rerank=not args.no_rerank)
        payload = {
            "meta": {
                "dataset": "C-MTEB/T2Retrieval",
                "kb_id": kb.id.hex,
                "pool_size": pool_size,
                "rerank": not args.no_rerank,
                "max_corpus": len(docs),
                "executed_queries": len(queries),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            "results": results,
        }
    save_json(RESULTS_PATH, payload)

    summary = summarize(results, BASE_K_VALUES)
    summary["meta"] = payload["meta"]
    save_json(SUMMARY_PATH, summary)

    lines = report_lines(
        "T2Retrieval 双路召回评测报告（受限语料）",
        payload["meta"],
        summary,
        BASE_K_VALUES,
        extra=[
            "> 受限语料口径：仅 corpus 前 1000 条文档建库；评测 query 为 qrels 中 gold "
            "全部落在库内的 query 全量，非 C-MTEB 官方全量评测。",
        ],
    )
    report_path = RESULTS_DIR / "t2retrieval_dual_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[t2] 汇总已落盘: {SUMMARY_PATH}；报告: {report_path}")
    m = summary["metrics"]
    print(
        f"[t2] 结果：MRR={m['mrr'][0]:.3f}，Recall@10={m[10]['recall'][0]:.3f}，"
        f"Precision@1={m[1]['precision'][0]:.3f}（有效 {summary['counts']['valid']} 条）"
    )


if __name__ == "__main__":
    asyncio.run(main())
