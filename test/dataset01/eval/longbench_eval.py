"""
zai-org/LongBench multifieldqa_zh 双路召回评测适配器（诊断性披露）。

LongBench 是问答数据集（无标准 retrieval qrels），本适配器采用"可辩护证据"
映射口径：query 的 answer 规范化后出现在某 context 段落文本中，则该段落为
gold（段落级 → 文档级）；answer 不可定位的 query 不参与指标，单独统计 why
（answer_not_in_context），不伪造指标。

- 建库：每条 query 的 context 按换行切分为段落，每段落一个文档（单块；
  超长段落走 ingest_file 切块），source_uri=lb:{qid}:{para_idx}。
- 管线：hybrid_retrieve_multi（dense + jieba BM25 RRF，candidate_pool=50）
  + rerank 精排（Qwen3-Embedding-4B cohere 协议），与生产配置一致。
- 指标：Recall@K / Precision@K / MRR（K∈{1,3,5,10}，文档级，宏平均±std），
  仅统计可辩护 query；结果标注"诊断性，不参与严格对比"。
- 产物：
  - gold/longbench_doc_map.json：lb 标识 → PG 文档 id 映射
  - results/longbench_dual_results.json：逐 query 明细
  - results/longbench_dual_summary.json：汇总指标 + why 统计

数据来源（HF）：THUDM/LongBench data.zip → multifieldqa_zh.jsonl（200 条全量）。

用法：
  uv run python test/dataset01/eval/longbench_eval.py [--force] [--cleanup]
      [--max-queries N] [--no-rerank] [--pool 50] [--retry-failed]
"""

import argparse
import asyncio
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from common import BASE_K_VALUES, DATA_DIR, GOLD_DIR, RESULTS_DIR, ensure_cfg_async, load_json, normalize, save_json

from dual_retrieval import (
    cleanup_kb,
    create_kb,
    find_kb,
    get_eval_session,
    ingest_document_retry,
    report_lines,
    run_eval,
    summarize,
    vectorize_batch,
)

KB_NAME = "dataset01-longbench"
KB_DESCRIPTION = "RAG 双路召回评测语料库：LongBench multifieldqa_zh（context 段落单块，诊断性）"

SUBSET = "multifieldqa_zh"
DATA_PATH = DATA_DIR / "longbench_data" / "data" / f"{SUBSET}.jsonl"
DOC_MAP_PATH = GOLD_DIR / "longbench_doc_map.json"
RESULTS_PATH = RESULTS_DIR / "longbench_dual_results.json"
SUMMARY_PATH = RESULTS_DIR / "longbench_dual_summary.json"


def _require_data() -> None:
    if not DATA_PATH.exists():
        raise SystemExit(
            f"缺少数据文件: {DATA_PATH}\n"
            "请从 HF 下载 THUDM/LongBench data.zip 并解压到 "
            "test/dataset01/data/longbench_data/（HF_ENDPOINT=https://hf-mirror.com）"
        )


def split_paragraphs(context: str) -> list[str]:
    """context 按换行切分为非空段落（去首尾空白）。"""
    return [p.strip() for p in context.split("\n") if p.strip()]


def defensible_paragraphs(context: str, answers: list[str]) -> tuple[list[int], str | None]:
    """可辩护证据映射：answer 规范化后子串命中段落 → 段落下标列表。

    返回 (gold_para_idx, why)；无可辩护段落时 why="answer_not_in_context"。
    """
    paras = split_paragraphs(context)
    norm_paras = [normalize(p) for p in paras]
    gold: list[int] = []
    for a in answers:
        norm_a = normalize(a)
        if not norm_a:
            continue
        for idx, np in enumerate(norm_paras):
            if norm_a in np:
                gold.append(idx)
    if gold:
        return sorted(set(gold)), None
    return [], "answer_not_in_context"


def load_rows() -> list[dict]:
    """读 multifieldqa_zh.jsonl，统一字段为 question/context/answers/_id。"""
    import json

    rows = []
    with open(DATA_PATH, encoding="utf-8") as fh:
        for line in fh:
            raw = json.loads(line)
            rows.append(
                {
                    "qid": str(raw["_id"]),
                    "question": str(raw.get("input") or ""),
                    "context": str(raw.get("context") or ""),
                    "answers": [str(a) for a in (raw.get("answers") or [])],
                }
            )
    return rows


async def build(session_factory, rows: list[dict], force: bool, batch_size: int = 100) -> object:
    """建库（幂等：KB 与 doc map 指纹一致时复用；--force 重建）。

    摄入走 ingest_document_retry（独立 session + DB 异常重试），
    规避评测目标机 PG 间歇断连。
    """
    fp = hashlib.sha256(
        ("\n".join(r["qid"] + r["context"][:200] for r in rows)).encode("utf-8")
    ).hexdigest()[:16]

    async with session_factory() as session:
        existing = await find_kb(session, KB_NAME)
        if existing is not None and not force:
            if DOC_MAP_PATH.exists():
                cached = load_json(DOC_MAP_PATH)
                if cached.get("fingerprint") == fp:
                    print(
                        f"[lb] 评测知识库已存在且指纹一致: {KB_NAME} id={existing.id.hex}"
                        f"（复用 {len(cached['mapping'])} 个段落映射，重建请加 --force）"
                    )
                    return existing, cached["mapping"]
            print(
                f"[lb] 评测知识库已存在但指纹不一致（重建请加 --force），"
                f"继续使用既有库: {existing.id.hex}"
            )
            return existing, {}

        if existing is not None and force:
            print(f"[lb] --force：清理既有评测知识库 {KB_NAME}...")
            await cleanup_kb(session, KB_NAME)

        kb = await create_kb(session, KB_NAME, KB_DESCRIPTION)
        await session.commit()
    print(f"[lb] 已创建评测知识库: {KB_NAME} id={kb.id.hex} collection={kb.qdrant_collection}")

    mapping: dict[str, str] = {}
    total_leaves = 0
    pending_specs: list[dict] = []
    processed = 0
    for row in rows:
        for para_idx, para in enumerate(split_paragraphs(row["context"])):
            uri = f"lb:{SUBSET}:{row['qid']}:{para_idx}"
            ingested, leaf_specs = await ingest_document_retry(
                session_factory,
                kb,
                title=uri,
                text=para,
                source_uri=uri,
                source_system="LongBench",
                metadata={"subset": SUBSET, "lb_qid": row["qid"], "para_idx": para_idx},
            )
            if ingested is None:
                continue
            mapping[uri] = ingested.id.hex
            total_leaves += len(leaf_specs)
            pending_specs.extend(leaf_specs)
            processed += 1
            if processed % batch_size == 0:
                await vectorize_batch(kb, pending_specs)
                print(f"[lb] 向量化 {processed} 段落（累计叶块 {total_leaves}）")
                pending_specs = []
    if pending_specs:
        await vectorize_batch(kb, pending_specs)
        print(f"[lb] 向量化收尾（累计叶块 {total_leaves}）")

    save_json(
        DOC_MAP_PATH,
        {
            "dataset": f"THUDM/LongBench {SUBSET}",
            "fingerprint": fp,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "kb_id": kb.id.hex,
            "mapping": mapping,
        },
    )
    print(f"[lb] 建库完成：{len(mapping)} 段落文档 / {total_leaves} 叶块")
    return kb, mapping


def build_queries(rows: list[dict], mapping: dict[str, str]) -> list[dict]:
    """构建评测 query 列表（gold = 可辩护段落 → PG 文档 id）。"""
    queries = []
    for row in rows:
        gold_docs = [
            mapping[f"lb:{SUBSET}:{row['qid']}:{i}"] for i in row["gold_para_idx"]
        ]
        queries.append(
            {
                "qid": row["qid"],
                "question": row["question"],
                "gold_docs": gold_docs,
                "why": row["why"],
            }
        )
    return queries


async def main() -> None:
    parser = argparse.ArgumentParser(description="LongBench multifieldqa_zh 双路召回评测（诊断性）")
    parser.add_argument("--force", action="store_true", help="已存在评测知识库时清理重建")
    parser.add_argument("--cleanup", action="store_true", help="整体删除评测知识库后退出")
    parser.add_argument("--max-queries", type=int, default=None, help="仅评测前 N 条 query（冒烟）")
    parser.add_argument("--no-rerank", action="store_true", help="跳过 rerank（仅双路召回检索层）")
    parser.add_argument("--pool", type=int, default=None, help="候选池大小（默认取系统 RAG_CANDIDATE_POOL_SIZE）")
    parser.add_argument("--retry-failed", action="store_true", help="仅补跑上次失败（status!=ok）的 query 并合并结果")
    args = parser.parse_args()

    await ensure_cfg_async()
    from core.config_snapshot import CFG

    _require_data()
    pool_size = args.pool or CFG.rag_candidate_pool_size

    if args.cleanup:
        async with get_eval_session() as session:
            removed = await cleanup_kb(session, KB_NAME)
        print(f"[lb] 已删除评测知识库 {KB_NAME}" if removed else f"[lb] 评测知识库 {KB_NAME} 不存在")
        return

    rows = load_rows()
    print(f"[lb] 数据就绪：{len(rows)} 条 query（{SUBSET} 全量）")

    # 可辩护证据映射（建库前完成，gold 为段落 → 文档）
    for row in rows:
        gold_idx, why = defensible_paragraphs(row["context"], row["answers"])
        row["gold_para_idx"] = gold_idx
        row["why"] = why
    defensible = sum(1 for r in rows if r["gold_para_idx"])
    print(
        f"[lb] 可辩护 query：{defensible}/{len(rows)}"
        f"（answer 子串命中 context 段落；其余计入 why=answer_not_in_context，不参与指标）"
    )

    async with get_eval_session() as session:
        kb, mapping = await build(get_eval_session, rows, args.force)
        if not mapping:
            from sqlalchemy import select

            from entity.rag.document import Document

            stmt = select(Document.id, Document.source_uri).where(
                Document.knowledge_base_id == kb.id
            )
            found = (await session.execute(stmt)).all()
            mapping = {r.source_uri: r.id.hex for r in found}
            print(f"[lb] 从 PG 重建段落映射：{len(mapping)} 个")

    queries = build_queries(rows, mapping)
    if args.max_queries:
        queries = queries[: args.max_queries]
    print(f"[lb] 执行 {len(queries)} 条 query（其中可辩护 {sum(1 for q in queries if q['gold_docs'])} 条）")

    if args.retry_failed:
        if not RESULTS_PATH.exists():
            raise SystemExit(f"--retry-failed 需要已有结果文件: {RESULTS_PATH}")
        prev = load_json(RESULTS_PATH)
        failed_qids = {r["qid"] for r in prev["results"] if r["status"] != "ok"}
        if not failed_qids:
            print("[lb] 无失败 query，无需补跑")
            return
        retry = [q for q in queries if q["qid"] in failed_qids]
        print(f"[lb] 补跑失败 query：{len(retry)} 条")
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
        print(
            f"[lb] 合并后结果：{len(results)} 条"
            f"（失败 {sum(1 for r in results if r['status'] != 'ok')}）"
        )
    else:
        results = await run_eval(queries, kb, pool_size, use_rerank=not args.no_rerank)
        payload = {
            "meta": {
                "dataset": f"longbench/{SUBSET}",
                "kb_id": kb.id.hex,
                "pool_size": pool_size,
                "rerank": not args.no_rerank,
                "executed_queries": len(queries),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            "results": results,
        }
    save_json(RESULTS_PATH, payload)

    summary = summarize(results, BASE_K_VALUES)
    summary["meta"] = payload["meta"]
    from collections import Counter

    summary["why"] = dict(Counter(q["why"] for q in queries if q["why"]))
    save_json(SUMMARY_PATH, summary)

    lines = report_lines(
        "LongBench multifieldqa_zh 双路召回评测报告（诊断性）",
        payload["meta"],
        summary,
        BASE_K_VALUES,
        extra=[
            f"- 可辩护 query：{summary['counts']['valid']}/{len(queries)}"
            f"（answer 可定位到 context 段落）；不可辩护统计：{summary.get('why')}",
            "",
            "> 诊断性披露：LongBench 无标准 retrieval qrels，gold 为 answer 子串命中的 "
            "context 段落（文档级）；不可辩护 query 不参与指标，不伪造 MRR。"
            "结果仅供参考，不参与严格对比。",
        ],
    )
    report_path = RESULTS_DIR / "longbench_dual_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[lb] 汇总已落盘: {SUMMARY_PATH}；报告: {report_path}")
    m = summary["metrics"]
    if m["mrr"]:
        print(
            f"[lb] 结果：MRR={m['mrr'][0]:.3f}，Recall@10={m[10]['recall'][0]:.3f}，"
            f"Precision@1={m[1]['precision'][0]:.3f}"
            f"（可辩护 {summary['counts']['valid']} 条）"
        )
    else:
        print("[lb] 结果：无可辩护 query，无指标")


if __name__ == "__main__":
    asyncio.run(main())
