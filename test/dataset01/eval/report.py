"""
S4 指标计算与报告：从 eval_results.json 汇总 Recall@K / Precision@K / NDCG@K / MRR，
输出 results/report.md（指标对比表 + K 曲线 + 失败案例抽样）。

- 双口径（严格 chunk 级 / 宽松文档级） × 双管线（纯检索 A / 完整子图 B）
- K ∈ {1, 3, 5, 10} ∪ {系统 RAG_FINAL_TOP_K}
- 宏平均 mean ± std；严格口径 gold 为空的 query 不计入指标（单独统计占比）

用法：
  uv run python test/dataset01/eval/report.py [--max-queries N]
"""

import argparse
import asyncio
from datetime import datetime, timezone

from common import (
    BASE_K_VALUES,
    CORPUS_STATS_PATH,
    EVAL_RESULTS_PATH,
    REPORT_PATH,
    ensure_cfg_async,
    final_top_k,
    load_json,
    mean_std,
)

# 失败案例抽样数（每口径）
FAILURE_CASE_SAMPLE = 3
# 候选片段截断长度（报告展示用）
SNIPPET_LENGTH = 120


def _collect_metrics(results: list[dict], ks: list[int]) -> dict:
    """
    按口径 × 管线收集每 query 指标。

    返回 {(mode, pipeline): {"recall": {k: [per-query]}, "precision": {k: [...]},
                             "ndcg": {k: [...]}, "mrr": [...],
                             "valid": n, "skipped_gold_empty": n}}
    mode: 'chunk'（严格）/ 'doc'（宽松）；pipeline: 'a' / 'b'
    """
    from common import compute_metrics

    acc: dict = {}
    for mode in ("chunk", "doc"):
        for pipeline in ("a", "b"):
            acc[(mode, pipeline)] = {
                "recall": {k: [] for k in ks},
                "precision": {k: [] for k in ks},
                "ndcg": {k: [] for k in ks},
                "mrr": [],
                "valid": 0,
                "skipped_gold_empty": 0,
            }

    for item in results:
        for mode, gold_key in (("chunk", "strict_gold"), ("doc", "relaxed_gold")):
            gold = item.get(gold_key) or []
            for pipeline in ("a", "b"):
                entry = acc[(mode, pipeline)]
                pipe = item.get(f"pipeline_{pipeline}") or {}
                if pipe.get("status") != "ok":
                    continue
                ranked = (
                    pipe.get("candidates") if pipeline == "a" else pipe.get("reranked")
                ) or []
                metrics = compute_metrics(ranked, gold, ks, mode=mode)
                if metrics is None:
                    entry["skipped_gold_empty"] += 1
                    continue
                entry["valid"] += 1
                entry["mrr"].append(metrics["mrr"])
                for k in ks:
                    entry["recall"][k].append(metrics[k]["recall"])
                    entry["precision"][k].append(metrics[k]["precision"])
                    entry["ndcg"][k].append(metrics[k]["ndcg"])
    return acc


def _fmt(value: tuple[float, float] | None) -> str:
    """指标单元格格式：mean±std 或 '—'（无有效样本）。"""
    if value is None:
        return "—"
    mean, std = value
    return f"{mean:.3f}±{std:.3f}"


def _metric_table(acc: dict, mode: str, ks: list[int], pipeline_b_enabled: bool) -> str:
    """单口径指标对比表：行 = K，列 = 双管线 Recall/Precision/NDCG + 增量，末行 MRR。"""
    lines = [
        "| K | Recall@K (A) | Recall@K (B) | Δ Recall | Precision@K (A) | Precision@K (B) | Δ Precision | NDCG@K (A) | NDCG@K (B) | Δ NDCG |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for k in ks:
        ra = _fmt(mean_std(acc[(mode, "a")]["recall"][k]))
        rb = (
            _fmt(mean_std(acc[(mode, "b")]["recall"][k])) if pipeline_b_enabled else "—"
        )
        pa = _fmt(mean_std(acc[(mode, "a")]["precision"][k]))
        pb = (
            _fmt(mean_std(acc[(mode, "b")]["precision"][k]))
            if pipeline_b_enabled
            else "—"
        )
        na = _fmt(mean_std(acc[(mode, "a")]["ndcg"][k]))
        nb = _fmt(mean_std(acc[(mode, "b")]["ndcg"][k])) if pipeline_b_enabled else "—"
        delta_r = _delta(acc, mode, "recall", k, pipeline_b_enabled)
        delta_p = _delta(acc, mode, "precision", k, pipeline_b_enabled)
        delta_n = _delta(acc, mode, "ndcg", k, pipeline_b_enabled)
        lines.append(
            f"| {k} | {ra} | {rb} | {delta_r} | {pa} | {pb} | {delta_p} | {na} | {nb} | {delta_n} |"
        )
    mrr_a = _fmt(mean_std(acc[(mode, "a")]["mrr"]))
    mrr_b = _fmt(mean_std(acc[(mode, "b")]["mrr"])) if pipeline_b_enabled else "—"
    delta_mrr = _delta(acc, mode, "mrr", None, pipeline_b_enabled)
    lines.append(f"| MRR | {mrr_a} | {mrr_b} | {delta_mrr} | — | — | — | — | — | — |")
    return "\n".join(lines)


def _delta(
    acc: dict, mode: str, metric: str, k: int | None, pipeline_b_enabled: bool
) -> str:
    """管线 B 相对 A 的指标增量（mean 差）。"""
    if not pipeline_b_enabled:
        return "—"
    if metric == "mrr":
        a = mean_std(acc[(mode, "a")]["mrr"])
        b = mean_std(acc[(mode, "b")]["mrr"])
    else:
        a = mean_std(acc[(mode, "a")][metric][k])
        b = mean_std(acc[(mode, "b")][metric][k])
    if a is None or b is None:
        return "—"
    delta = b[0] - a[0]
    return f"{delta:+.3f}"


def _failure_cases(results: list[dict], mode: str, limit: int) -> list[dict]:
    """MRR=0 且 gold 非空的 query 抽样（含 top-3 候选片段，供人工分析）。"""
    from common import hit_positions

    cases = []
    for item in results:
        gold_key = "strict_gold" if mode == "chunk" else "relaxed_gold"
        gold = item.get(gold_key) or []
        if not gold:
            continue
        for pipeline in ("a", "b"):
            pipe = item.get(f"pipeline_{pipeline}") or {}
            if pipe.get("status") != "ok":
                continue
            ranked = (
                pipe.get("candidates") if pipeline == "a" else pipe.get("reranked")
            ) or []
            if hit_positions(ranked, gold, mode=mode):
                continue
            cases.append(
                {
                    "row_index": item["row_index"],
                    "question": (item.get("question") or "")[:100],
                    "pipeline": "A 纯检索" if pipeline == "a" else "B 完整子图",
                    "top_candidates": [
                        (cand.get("text") or "")[:SNIPPET_LENGTH] for cand in ranked[:3]
                    ],
                }
            )
            if len(cases) >= limit:
                return cases
    return cases


async def report(max_queries: int | None) -> None:
    await ensure_cfg_async()
    payload = load_json(EVAL_RESULTS_PATH)
    stats = load_json(CORPUS_STATS_PATH)
    meta = payload["meta"]
    results = payload["results"][:max_queries] if max_queries else payload["results"]

    ks = sorted(set([*BASE_K_VALUES, final_top_k()]))
    pipeline_b_enabled = not meta.get("no_graph", False)
    acc = _collect_metrics(results, ks)

    # 有效样本与空占比（严格口径）
    valid_a = acc[("chunk", "a")]["valid"]
    skipped = acc[("chunk", "a")]["skipped_gold_empty"]
    failed_a = sum(1 for r in results if r["pipeline_a"]["status"] == "failed")
    failed_b = sum(
        1
        for r in results
        if pipeline_b_enabled and r["pipeline_b"]["status"] == "failed"
    )

    lines: list[str] = [
        "# RAG 检索质量评测报告（dataset01：农业维基 QA 110K）",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        f"- 数据集：{stats.get('dataset', '')}（sha256: {str(stats.get('csv_sha256', ''))[:12]}）",
        f"- 记录数：{stats.get('records')} / 页面数：{stats.get('pages')} / "
        f"文档数：{stats.get('documents')} / 叶块数：{stats.get('leaf_chunks')}",
        f"- 评测知识库：{meta.get('kb_id')}（seed={meta.get('seed')}，"
        f"sample_size={meta.get('sample_size')}，执行 {len(results)} 条）",
        f"- 系统配置：candidate_pool={meta.get('candidate_pool_size')}，"
        f"final_top_k={meta.get('final_top_k')}，reflect_round_cap={meta.get('reflect_round_cap')}",
        f"- 管线：A 纯检索（dense+sparse RRF）{'、B 完整子图（反思+重排）' if pipeline_b_enabled else ''}",
        f"- 失败计数：A 失败 {failed_a} 条，B 失败 {failed_b} 条（已从指标中剔除）",
        "",
    ]

    if skipped > 0:
        ratio = skipped / len(results) if results else 0
        lines.append(
            f"> ⚠️ 严格口径下 {skipped}/{len(results)}（{ratio:.1%}）条 query 的 content "
            "未匹配到任何叶块（gold 为空），不计入严格口径指标。"
        )
        lines.append("")

    lines.append("## 严格口径指标（chunk 级：叶块文本包含 content）")
    lines.append("")
    lines.append(_metric_table(acc, "chunk", ks, pipeline_b_enabled))
    lines.append("")
    lines.append(
        f"有效 query 数：{acc[('chunk', 'a')]['valid']}（A）"
        + (f" / {acc[('chunk', 'b')]['valid']}（B）" if pipeline_b_enabled else "")
    )
    lines.append("")
    lines.append("## 宽松口径指标（文档级：同 pageid 任意叶块）")
    lines.append("")
    lines.append(_metric_table(acc, "doc", ks, pipeline_b_enabled))
    lines.append("")
    lines.append(
        f"有效 query 数：{acc[('doc', 'a')]['valid']}（A）"
        + (f" / {acc[('doc', 'b')]['valid']}（B）" if pipeline_b_enabled else "")
    )
    lines.append("")
    lines.append(
        "> 注：Δ 列为完整子图（B）相对纯检索（A）的 mean 增量；NDCG 为二值相关性标准式（DCG/IDCG）；K 曲线即上表 Recall@K 随 K 的变化。"
    )
    lines.append("")

    lines.append("## 失败案例抽样（MRR=0 且 gold 非空，每口径 3 条）")
    for mode, label in (("chunk", "严格口径"), ("doc", "宽松口径")):
        cases = _failure_cases(results, mode, FAILURE_CASE_SAMPLE)
        lines.append("")
        lines.append(f"### {label}")
        if not cases:
            lines.append("（无）")
            continue
        for case in cases:
            lines.append(
                f"- **Q**（row {case['row_index']}，{case['pipeline']}）：{case['question']}"
            )
            for i, snippet in enumerate(case["top_candidates"], start=1):
                lines.append(f"  - top-{i}: {snippet}")
    lines.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[S4] 报告已生成: {REPORT_PATH}（{len(results)} 条 query）")


async def main() -> None:
    parser = argparse.ArgumentParser(description="S4 指标计算与报告")
    parser.add_argument(
        "--max-queries", type=int, default=None, help="仅统计前 N 条结果（冒烟）"
    )
    args = parser.parse_args()
    await report(args.max_queries)


if __name__ == "__main__":
    asyncio.run(main())
