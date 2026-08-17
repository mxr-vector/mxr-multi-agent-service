"""
LongBench 生产工具级评测（对齐生产 Agentic 工具调用）。

与 longbench_eval.py（dual，检索层下界）的区分：
- dual 检索层下界：原始 query → hybrid_retrieve_multi 单轮混合召回 → rerank
  （全池 50 精排不裁剪）——衡量单次检索的召回极限；
- tool 生产工具级：原始 query → knowledge_base_search_impl（生产
  knowledge_base_search 工具完整实现）= 混合召回 + 反思充分性判定
  （compression 模型）+ 改写查询重检（上限 CFG.rag_reflect_round_cap）
  + rerank 裁剪（top_k=10）——对齐生产 Agentic 管线中单次工具调用的真实
  行为（LLM 是否检索/逐跳拆解仍不在本评测范围，见 RAG.md 4.2 要点）。

复用同一 gold 口径（可辩护证据映射 v2，见 longbench_eval）与同一批评测
知识库（5 子集独立库，gold/longbench_doc_map.json 复用建库产物），指标口径
一致（文档级 v2），产物命名 tool 与 dual 区分。

产物：
- results/longbench_tool_results.json：逐 query 明细
- results/longbench_tool_summary.json：整体汇总 + why 统计
- results/longbench_tool_{subset}_summary.json：每子集独立汇总
- results/longbench_tool_report.md：报告（整体表 + 按子集分节）

用法：
  uv run python test/dataset01/eval/longbench_tool_eval.py [--max-queries N]
      [--subsets s1,s2,...]
"""

import argparse
import asyncio
import time
from collections import Counter
from datetime import datetime, timezone

from common import BASE_K_VALUES, RESULTS_DIR, ensure_cfg_async, load_json, save_json

from dual_retrieval import fmt_ms, report_lines, summarize
from longbench_eval import (
    DEFAULT_MAX_QUERIES,
    DOC_MAP_PATH,
    SUBSETS,
    SUBSET_INFO,
    _data_path,
    defensible_paragraphs,
    load_rows,
)

# rerank 裁剪目标：覆盖指标 K 档位（1/3/5/10）
TOOL_TOP_K = 10
# 工具调用并发（与 dual 评测 CONCURRENCY 一致；工具内含 LLM 反思判定与改写，
# 本地 vLLM 服务 4 并发安全）
TOOL_CONCURRENCY = 4
# 单条工具调用超时（秒）：rewrite 云服务（stepfun）偶发挂起（实测 >30min 无响应），
# 客户端无超时配置，评测侧兜底放弃该条并继续，避免整体卡死
TOOL_TIMEOUT = 240
# 断点续跑：每批执行完增量落盘，中途挂起可续跑不重算
CHECKPOINT_PATH = RESULTS_DIR / "longbench_tool_results_partial.json"
CHECKPOINT_CHUNK = 100


def _require_doc_map() -> dict:
    """复用 dual 建库产物：doc map（uri→文档 id + 子集 kb id）。

    缺失时提示先跑 longbench_eval.py 建库（两评测共用同一批评测知识库）。
    """
    if not DOC_MAP_PATH.exists():
        raise SystemExit(
            f"缺少建库产物: {DOC_MAP_PATH}\n"
            "请先运行 uv run python test/dataset01/eval/longbench_eval.py"
            "（建库 + gold 口径 v2 产物，两评测共用）"
        )
    return load_json(DOC_MAP_PATH)


async def run_tool_queries(queries: list[dict], concurrency: int = TOOL_CONCURRENCY) -> list[dict]:
    """逐 query 调用生产 knowledge_base_search_impl（工具完整实现，含反思改写重检）。

    queries: [{qid, subset, question, gold_docs, kb_hex}]；
    单条工具调用受 TOOL_TIMEOUT 兜底（rewrite 云服务偶发挂起），超时/异常记
    status=timeout/failed 不拖垮整体。
    返回 [{qid, question, gold_docs, status, candidates, reflect_rounds,
    retrieved_count, latency_ms, error}]，candidates 含
    document_id/score/text（rerank 后得分）。
    """
    from agent.tools.rag_tools import knowledge_base_search_impl

    sem = asyncio.Semaphore(concurrency)

    async def one(q: dict) -> dict:
        async with sem:
            started = time.monotonic()
            try:
                async with asyncio.timeout(TOOL_TIMEOUT):
                    outcome = await knowledge_base_search_impl(
                        q["question"], [q["kb_hex"]], top_k=TOOL_TOP_K
                    )
                return {
                    "qid": q["qid"],
                    "question": q["question"],
                    "gold_docs": q["gold_docs"],
                    "status": "ok",
                    "candidates": [
                        {
                            "document_id": doc.get("document_id"),
                            "score": doc.get("score"),
                            "text": doc.get("text", ""),
                        }
                        for doc in outcome.docs
                    ],
                    "reflect_rounds": outcome.metrics.get("reflect_rounds", 0),
                    "retrieved_count": outcome.metrics.get("retrieved_count", 0),
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
            except TimeoutError:
                return {
                    "qid": q["qid"],
                    "question": q["question"],
                    "gold_docs": q["gold_docs"],
                    "status": "timeout",
                    "candidates": [],
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "error": f"工具调用超时（>{TOOL_TIMEOUT}s，rewrite 云服务疑似挂起）",
                }
            except Exception as exc:
                return {
                    "qid": q["qid"],
                    "question": q["question"],
                    "gold_docs": q["gold_docs"],
                    "status": "failed",
                    "candidates": [],
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "error": f"{type(exc).__name__}: {exc}",
                }

    return await asyncio.gather(*(one(q) for q in queries))


def _subset_of(qid: str) -> str:
    """从 qid（{subset}:{_id}）提取子集名。"""
    return qid.split(":", 1)[0]


def _subset_section_lines(subset: str, summary: dict, ks) -> list[str]:
    """单子集报告分节：标题 + 指标表 + 可辩护统计。"""
    info = SUBSET_INFO.get(subset, {})
    label = f"{subset}（{info.get('lang', '')}，{info.get('task', '')}）"
    counts = summary["counts"]
    metrics = summary["metrics"]
    lines = [
        f"### {label}",
        "",
        f"- 执行 query：{counts['valid'] + counts['empty_gold'] + counts['failed']} 条"
        f"（有效 {counts['valid']} / gold 为空 {counts['empty_gold']} / 失败 {counts['failed']}）",
    ]
    if summary.get("why"):
        lines.append(f"- 不可辩护统计：{summary['why']}")
    lines.extend(["", "| K | Recall@K | Precision@K | NDCG@K |", "|---|---|---|---|"])
    for k in ks:
        k = int(k)
        lines.append(
            f"| {k} | {fmt_ms(metrics[k]['recall'])} | {fmt_ms(metrics[k]['precision'])} | {fmt_ms(metrics[k]['ndcg'])} |"
        )
    lines.append(f"| MRR | {fmt_ms(metrics['mrr'])} | — | — |")
    return lines


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="LongBench 生产工具级评测（对齐生产 Agentic 工具调用）"
    )
    parser.add_argument(
        "--subsets",
        type=str,
        default=",".join(SUBSETS),
        help="评测子集列表（逗号分隔，默认全 5 个）",
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=DEFAULT_MAX_QUERIES,
        help=f"仅评测前 N 条 query（默认 {DEFAULT_MAX_QUERIES}；冒烟可设小值）",
    )
    args = parser.parse_args()

    await ensure_cfg_async()
    from core.config_snapshot import CFG

    subsets = [s.strip() for s in args.subsets.split(",") if s.strip()]
    missing = [s for s in subsets if not _data_path(s).exists()]
    if missing:
        raise SystemExit(f"缺少数据文件: {[_data_path(s) for s in missing]}")

    rows = load_rows(subsets)
    print(f"[tool] 数据就绪：{len(rows)} 条 query（{dict(Counter(r['subset'] for r in rows))}）")

    # 可辩护证据映射（与 dual 同口径 v2，gold 为段落 → 文档）
    for row in rows:
        gold_idx, why = defensible_paragraphs(row["context"], row["answers"])
        row["gold_para_idx"] = gold_idx
        row["why"] = why
    defensible = sum(1 for r in rows if r["gold_para_idx"])
    why_counter = Counter(r["why"] for r in rows if r["why"])
    print(
        f"[tool] 可辩护 query：{defensible}/{len(rows)}；不可辩护：{dict(why_counter)}"
    )

    doc_map = _require_doc_map()
    mapping = doc_map["mapping"]
    kb_ids = doc_map["kb_ids"]
    missing_kb = [s for s in subsets if s not in kb_ids]
    if missing_kb:
        raise SystemExit(f"doc map 缺少子集知识库 id: {missing_kb}")
    print(
        f"[tool] 复用建库产物：{len(mapping)} 段落映射 / {len(kb_ids)} 个子集库"
        f"（reflect cap={CFG.rag_reflect_round_cap}，candidate pool={CFG.rag_candidate_pool_size}）"
    )

    queries = []
    for row in rows:
        gold_docs = sorted(
            {
                mapping[f"lb:{row['qid']}:{i}"]
                for i in row["gold_para_idx"]
                if f"lb:{row['qid']}:{i}" in mapping
            }
        )
        queries.append(
            {
                "qid": row["qid"],
                "subset": row["subset"],
                "question": row["question"],
                "gold_docs": gold_docs,
                "why": row["why"],
                "kb_hex": kb_ids[row["subset"]],
            }
        )
    if args.max_queries:
        queries = queries[: args.max_queries]
    print(
        f"[tool] 执行 {len(queries)} 条 query（其中可辩护 {sum(1 for q in queries if q['gold_docs'])} 条）"
    )

    # 断点续跑：复用已落盘结果，跳过已完成 qid（每批执行完增量保存）
    results: list[dict] = []
    if CHECKPOINT_PATH.exists():
        prev = load_json(CHECKPOINT_PATH)
        prev_results = prev.get("results") or []
        results = [r for r in prev_results if r["qid"] in {q["qid"] for q in queries}]
        print(f"[tool] 断点续跑：已复用 {len(results)} 条既有结果，继续剩余 {len(queries) - len(results)} 条")
    done_qids = {r["qid"] for r in results}
    pending = [q for q in queries if q["qid"] not in done_qids]
    for start in range(0, len(pending), CHECKPOINT_CHUNK):
        batch = pending[start : start + CHECKPOINT_CHUNK]
        results.extend(await run_tool_queries(batch))
        save_json(CHECKPOINT_PATH, {"meta": {"created_at": datetime.now(timezone.utc).isoformat()}, "results": results})
        print(
            f"[tool] 进度 {len(results)}/{len(queries)}"
            f"（成功 {sum(1 for r in results if r['status'] == 'ok')}）"
        )

    payload = {
        "meta": {
            "dataset": f"zai-org/LongBench 多语言（{'/'.join(subsets)}）",
            "kb_id": "各子集独立库（"
            + ", ".join(f"{s}={kb_ids[s][:8]}" for s in subsets)
            + "）",
            "pool_size": CFG.rag_candidate_pool_size,
            "rerank": True,
            "pipeline": "生产工具级 knowledge_base_search_impl"
            f"（混合召回 + 反思改写重检 cap={CFG.rag_reflect_round_cap} + rerank top_k={TOOL_TOP_K}）",
            "subsets": subsets,
            "executed_queries": len(queries),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        "results": results,
    }
    save_json(RESULTS_DIR / "longbench_tool_results.json", payload)
    # 全部完成：清理断点文件（避免下次误复用过期结果）
    if CHECKPOINT_PATH.exists():
        CHECKPOINT_PATH.unlink()

    summary = summarize(results, BASE_K_VALUES)
    summary["meta"] = payload["meta"]
    summary["why"] = dict(Counter(q["why"] for q in queries if q["why"]))
    # 工具级统计：反思轮数与平均时延（dual 无此维度）
    ok = [r for r in results if r["status"] == "ok"]
    summary["tool_stats"] = {
        "avg_reflect_rounds": round(
            sum(r.get("reflect_rounds", 0) for r in ok) / len(ok), 2
        )
        if ok
        else None,
        "avg_latency_ms": sum(r.get("latency_ms", 0) for r in ok) // len(ok)
        if ok
        else None,
    }
    save_json(RESULTS_DIR / "longbench_tool_summary.json", summary)

    per_subset: dict[str, dict] = {}
    for subset in subsets:
        sub_results = [r for r in results if _subset_of(r["qid"]) == subset]
        sub_queries = [q for q in queries if _subset_of(q["qid"]) == subset]
        sub_summary = summarize(sub_results, BASE_K_VALUES)
        sub_summary["meta"] = payload["meta"]
        sub_summary["why"] = dict(Counter(q["why"] for q in sub_queries if q["why"]))
        per_subset[subset] = sub_summary
        save_json(RESULTS_DIR / f"longbench_tool_{subset}_summary.json", sub_summary)

    ts = summary.get("tool_stats") or {}
    lines = report_lines(
        "LongBench 生产工具级评测报告（对齐生产 Agentic 工具调用）",
        payload["meta"],
        summary,
        BASE_K_VALUES,
        extra=[
            f"- 可辩护 query：{summary['counts']['valid']}/{len(queries)}"
            f"（answer 可定位到 context 段落）；不可辩护统计：{summary.get('why')}",
            f"- 工具统计：平均反思轮数 {ts.get('avg_reflect_rounds')}，"
            f"平均耗时 {ts.get('avg_latency_ms')} ms/条",
            "",
            "> 口径限定：本评测调用生产 knowledge_base_search 工具完整实现（混合召回 +"
            "反思充分性判定 + 改写查询重检 + rerank 裁剪 top_k=10），与检索层下界"
            "（dual，单轮混合召回 + rerank，见 longbench_dual_report.md）区分：本口径"
            "额外覆盖工具内反思改写重检；LLM 是否检索、逐跳拆解等 Agentic 外层决策"
            "仍不在范围内。gold 口径同 v2 可辩护证据映射，局限见 RAG.md 4.2 节。",
        ],
    )
    lines.extend(["", "## 按子集拆分（中英文 / 任务类型标注）", ""])
    for subset in subsets:
        lines.extend(_subset_section_lines(subset, per_subset[subset], BASE_K_VALUES))
        lines.append("")
    report_path = RESULTS_DIR / "longbench_tool_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[tool] 汇总已落盘: longbench_tool_summary.json；分集汇总: {len(per_subset)} 份；报告: {report_path}")
    m = summary["metrics"]
    if m["mrr"]:
        print(
            f"[tool] 结果：MRR={m['mrr'][0]:.3f}，Recall@10={m[10]['recall'][0]:.3f}，"
            f"Precision@1={m[1]['precision'][0]:.3f}（可辩护 {summary['counts']['valid']} 条）"
        )
    else:
        print("[tool] 结果：无可辩护 query，无指标")


if __name__ == "__main__":
    asyncio.run(main())
