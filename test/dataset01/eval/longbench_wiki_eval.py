"""LongBench v3 comparison: wiki-guided evidence retrieval vs no-wiki baseline."""

from __future__ import annotations

import argparse
import asyncio
import time
from collections import Counter
from datetime import datetime, timezone

from common import BASE_K_VALUES, RESULTS_DIR, ensure_cfg_async, load_json, save_json
from longbench_eval import DEFAULT_MAX_QUERIES, DOC_MAP_PATH, SUBSETS, _data_path, load_rows
from v3 import attach_v3_gold, render_v3_report, summarize_v3

RESULTS_PATH = RESULTS_DIR / "longbench_v3_wiki_results.json"
SUMMARY_PATH = RESULTS_DIR / "longbench_v3_wiki_summary.json"
REPORT_PATH = RESULTS_DIR / "longbench_v3_wiki_report.md"
CONCURRENCY = 4
TIMEOUT = 240


async def run_queries(rows: list[dict], concurrency: int = CONCURRENCY, multihop: bool = True,
                      multihop_only_multihop: bool = False) -> list[dict]:
    from agent.tools.rag_tools import (
        kb_wiki_lookup_impl,
        knowledge_base_search_impl,
    )

    semaphore = asyncio.Semaphore(concurrency)

    async def one(row: dict) -> dict:
        async with semaphore:
            started = time.monotonic()
            output = {
                "qid": row["qid"],
                "question": row["question"],
                "answer_gold_docs": row.get("answer_gold_docs", []),
                "bridge_gold_docs": row.get("bridge_gold_docs", []),
                "hop_gold_docs": row.get("hop_gold_docs", []),
                "gold_origin": row.get("gold_origin"),
                "question_type": row.get("question_type"),
                "hop_count": row.get("hop_count"),
                "status": "ok",
                "candidates": [],
                "wiki_hits": 0,
                "online_llm_calls": 0,
                "hops_executed": 0,
                "hop_queries": [],
                "hop_gold_attribution": [],
                "navigation_effective_pages": 0,
                "navigation_generic_pages": 0,
                "degraded": False,
            }
            try:
                async with asyncio.timeout(TIMEOUT):
                    wiki = await kb_wiki_lookup_impl(
                        row["question"], row.get("wiki_scopes") or [row["kb_hex"]], top_k=5
                    )
                    output["wiki_hits"] = wiki.metrics.get("wiki_hits", 0)
                    evidence = await knowledge_base_search_impl(
                        row["question"],
                        [row["kb_hex"]],
                        top_k=10,
                        navigation=wiki.navigation,
                        multihop=multihop and (
                            not multihop_only_multihop
                            or row.get("question_type") == "multi-hop"
                        ),
                    )
                output["candidates"] = [
                    {
                        "document_id": doc.get("document_id"),
                        "score": doc.get("score"),
                        "text": doc.get("text", ""),
                        "source_hops": doc.get("source_hops"),
                    }
                    for doc in evidence.docs
                ]
                metrics = evidence.metrics
                # Navigation-guided retrieval intentionally bypasses the old
                # reflection/rewrite loop; count only those internal calls.
                output["online_llm_calls"] = max(
                    0, (metrics.get("reflect_rounds", 0) - 1) * 2
                )
                output["hops_executed"] = metrics.get("hops_executed", 0)
                output["hop_queries"] = metrics.get("hop_queries", [])
                output["navigation_effective_pages"] = metrics.get("navigation_effective_pages", 0)
                output["navigation_generic_pages"] = metrics.get("navigation_generic_pages", 0)
                output["degraded"] = bool(metrics.get("degraded")) or bool(metrics.get("degraded_reason"))
                # 逐跳 gold 归因（D6）：每个跳组 gold 在最终 top-k / 逐跳候选池 /
                # 全部未命中三态定位失败阶段（裁剪 vs 召回）
                final_ids = {c["document_id"] for c in output["candidates"]}
                pools = {
                    int(hop): set(ids)
                    for hop, ids in (metrics.get("hop_pools") or {}).items()
                }
                all_pool_ids = set().union(*pools.values()) if pools else set()
                for hop_idx, group in enumerate(row.get("hop_gold_docs") or []):
                    gold = {str(g) for g in group if g}
                    if not gold:
                        continue
                    if gold & final_ids:
                        stage = "final_top10"
                    elif gold & all_pool_ids:
                        stage = "pool_trimmed"
                    else:
                        stage = "recall_missed"
                    output["hop_gold_attribution"].append(
                        {
                            "hop_group": hop_idx,
                            "stage": stage,
                            "gold_count": len(gold),
                        }
                    )
            except TimeoutError:
                output["status"] = "timeout"
                output["error"] = f"wiki-guided query timed out after {TIMEOUT}s"
            except Exception as exc:
                output["status"] = "failed"
                output["error"] = f"{type(exc).__name__}: {exc}"
            output["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
            return output

    return await asyncio.gather(*(one(row) for row in rows))


def render_multihop_diagnostics(results: list[dict]) -> str:
    """Multihop path diagnostics: per-hop attribution, nav effectiveness,
    degradation denominators, and the annotated 2-hop hop@10 0.80 target."""
    from collections import Counter

    ok = [item for item in results if item.get("status") == "ok"]
    timeouts = sum(1 for item in results if item.get("status") == "timeout")
    failed = sum(1 for item in results if item.get("status") == "failed")
    with_wiki = [item for item in ok if item.get("wiki_hits", 0) > 0]
    nav_effective = [item for item in with_wiki if item.get("navigation_effective_pages", 0) > 0]
    degraded = [item for item in ok if item.get("degraded")]
    attribution = Counter(
        entry["stage"] for item in ok for entry in item.get("hop_gold_attribution") or []
    )
    total_groups = sum(attribution.values())

    # 标注型两跳验收口径（0.80 目标；完整分母，不剔除失败样本）
    target_rows = [
        item for item in results
        if item.get("gold_origin") == "annotated" and item.get("hop_count") == 2
    ]
    target_ok = [item for item in target_rows if item.get("status") == "ok"]
    group_total = group_success = 0
    for item in target_ok:
        final_ids = {c["document_id"] for c in item.get("candidates") or []}
        for group in item.get("hop_gold_docs") or []:
            gold = {str(g) for g in group if g}
            if not gold:
                continue
            group_total += 1
            if gold & final_ids:
                group_success += 1
    target_rate = group_success / group_total if group_total else None

    lines = [
        "",
        "## Multihop diagnostics",
        "",
        f"- 分母完整性: executed={len(results)}, ok={len(ok)}, timeout={timeouts}, failed={failed}",
        f"- 导航有效率: {len(nav_effective)}/{len(with_wiki)}"
        f" = {len(nav_effective) / len(with_wiki):.1%}（命中 wiki 且页面含问题实体/成员重合）" if with_wiki else "- 导航有效率: 无 wiki 命中",
        f"- 降级样本: {len(degraded)}（后续跳异常但保留已完成跳候选）",
        f"- 平均执行跳数: {sum(item.get('hops_executed', 0) for item in ok) / len(ok):.2f}" if ok else "",
        "",
        "### 逐跳 gold 归因（按跳组计数）",
        "",
        "| 阶段 | 跳组数 | 占比 |",
        "|---|---|---|",
    ]
    for stage, label in (
        ("final_top10", "最终 top-10 命中"),
        ("pool_trimmed", "在候选池但被合并/终排丢失"),
        ("recall_missed", "逐跳召回均未命中"),
    ):
        count = attribution.get(stage, 0)
        ratio = count / total_groups if total_groups else 0.0
        lines.append(f"| {label} | {count} | {ratio:.1%} |")

    # 实体扩展通道已于 agentic 路线切换时整体移除（见归档报告），
    # 桥接证据改由 agent 经 entity_relation_lookup 自主消费。
    lines += [
        "",
        "### 实体扩展通道",
        "",
        "- 已移除（评测证伪后删除；桥接证据改由 agent 经 entity_relation_lookup 消费）",
    ]
    lines += [
        "",
        "### 标注型两跳验收口径（目标 hop_success@10 = 0.80）",
        "",
        f"- 样本: {len(target_rows)} 条 query（ok {len(target_ok)}，非 ok {len(target_rows) - len(target_ok)} 计入分母披露）",
        f"- 跳组命中: {group_success}/{group_total}"
        + (f" = {target_rate:.3f}" if target_rate is not None else "（无有效跳组）"),
        f"- 目标达成: {'是' if target_rate is not None and target_rate >= 0.80 else '否'}" if target_rate is not None else "- 目标达成: 无法判定",
    ]
    return "\n".join(lines) + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser(description="LongBench v3 wiki comparison")
    parser.add_argument("--subsets", default=",".join(SUBSETS))
    parser.add_argument("--max-queries", type=int, default=DEFAULT_MAX_QUERIES)
    parser.add_argument("--wiki-scope", default=None, help="override wiki collection scope for every query")
    parser.add_argument("--no-multihop", action="store_true", help="关闭逐跳下钻（旧单轮导航对照）")
    parser.add_argument("--multihop-only-multihop", action="store_true",
                        help="仅多跳题启用逐跳（生产真实语义：agent 只对多跳题传 multihop=True）")
    parser.add_argument("--retry-failed", action="store_true", help="仅补跑上次失败/超时 query 并合并结果")
    args = parser.parse_args()
    subsets = [item.strip() for item in args.subsets.split(",") if item.strip()]
    missing = [str(_data_path(item)) for item in subsets if not _data_path(item).exists()]
    if missing:
        raise SystemExit(f"Missing LongBench data files: {missing}")
    await ensure_cfg_async()
    if not DOC_MAP_PATH.exists():
        raise SystemExit(f"Missing document map: {DOC_MAP_PATH}; run longbench_eval.py first")
    doc_map = load_json(DOC_MAP_PATH)
    rows = [attach_v3_gold(row, doc_map.get("mapping") or {}) for row in load_rows(subsets)]
    rows = rows[: args.max_queries] if args.max_queries else rows
    queries = []
    for row in rows:
        evidence_kb_hex = (doc_map.get("kb_ids") or {}).get(row["subset"])
        if not evidence_kb_hex:
            continue
        row = dict(row)
        row["kb_hex"] = evidence_kb_hex
        row["wiki_scopes"] = [args.wiki_scope or evidence_kb_hex]
        queries.append(row)
    prior_results: dict[str, dict] = {}
    if args.retry_failed:
        if not RESULTS_PATH.exists():
            raise SystemExit("--retry-failed 需要已有结果文件")
        prior = load_json(RESULTS_PATH).get("results") or []
        prior_results = {item["qid"]: item for item in prior}
        failed_qids = {qid for qid, item in prior_results.items() if item.get("status") != "ok"}
        queries = [q for q in queries if q["qid"] in failed_qids]
        print(f"[v3-wiki] retry-failed: 补跑 {len(queries)} 条", flush=True)
    results = await run_queries(queries, multihop=not args.no_multihop,
                                multihop_only_multihop=args.multihop_only_multihop)
    if prior_results:
        merged = {item["qid"]: item for item in results}
        for qid, item in prior_results.items():
            if qid not in merged:
                merged[qid] = item
        results = list(merged.values())
    meta = {
        "dataset": "zai-org/LongBench five-subset",
        "pipeline": (
            "kb_wiki_lookup -> multihop knowledge_base_search (per-hop recall/rerank, gated navigation)"
            if not args.no_multihop
            else "kb_wiki_lookup -> original-query knowledge_base_search (navigation context only)"
        ),
        "subsets": subsets,
        "executed_queries": len(results),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    save_json(RESULTS_PATH, {"meta": meta, "results": results})
    disclosure = summarize_v3(results, BASE_K_VALUES)
    strict = summarize_v3(results, BASE_K_VALUES, strict_only=True)
    ok = [item for item in results if item.get("status") == "ok"]
    cost = {
        "wiki_calls": len(ok),
        "queries_with_wiki_hits": sum(item.get("wiki_hits", 0) > 0 for item in ok),
        "wiki_hit_rate": (
            sum(item.get("wiki_hits", 0) > 0 for item in ok) / len(ok) if ok else 0.0
        ),
        "navigation_effective_rate": (
            sum(item.get("navigation_effective_pages", 0) > 0 for item in ok if item.get("wiki_hits", 0) > 0)
            / max(1, sum(1 for item in ok if item.get("wiki_hits", 0) > 0))
        ),
        "degraded_queries": sum(1 for item in ok if item.get("degraded")),
        "timeout_queries": sum(1 for item in results if item.get("status") == "timeout"),
        "failed_queries": sum(1 for item in results if item.get("status") == "failed"),
        "avg_hops_executed": (
            sum(item.get("hops_executed", 0) for item in ok) / len(ok) if ok else 0.0
        ),
        "avg_online_llm_calls_inside_evidence_tool": (
            sum(item.get("online_llm_calls", 0) for item in ok) / len(ok) if ok else 0.0
        ),
        "avg_latency_ms": sum(item.get("latency_ms", 0) for item in ok) / len(ok) if ok else 0.0,
    }
    summary = {"meta": meta, "disclosure": disclosure, "strict": strict, "cost": cost}
    save_json(SUMMARY_PATH, summary)
    report = render_v3_report(
        "LongBench v3 wiki-guided evaluation", {**meta, **cost}, disclosure, strict
    )
    report += render_multihop_diagnostics(results)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"[v3-wiki] report written: {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
