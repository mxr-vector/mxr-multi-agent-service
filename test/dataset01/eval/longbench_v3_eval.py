"""Run the current no-wiki LongBench pipeline with v3 evidence accounting.

The runner deliberately reuses the existing LongBench corpus/doc-map and
retrieval implementation.  It changes only the gold and reporting layer, so
the output is a clean baseline for a later wiki-enabled comparison.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from common import BASE_K_VALUES, GOLD_DIR, RESULTS_DIR, ensure_cfg_async, load_json, save_json
from dual_retrieval import run_eval
from longbench_eval import (
    DEFAULT_MAX_QUERIES,
    DOC_MAP_PATH,
    SUBSETS,
    _data_path,
    load_rows,
)
from v3 import attach_v3_gold, render_v3_report, summarize_v3

RESULTS_PATH = RESULTS_DIR / "longbench_v3_baseline_results.json"
SUMMARY_PATH = RESULTS_DIR / "longbench_v3_baseline_summary.json"
REPORT_PATH = RESULTS_DIR / "longbench_v3_baseline_report.md"


def _require_doc_map() -> dict:
    if not DOC_MAP_PATH.exists():
        raise SystemExit(
            f"Missing corpus document map: {DOC_MAP_PATH}. Run longbench_eval.py first."
        )
    return load_json(DOC_MAP_PATH)


async def main() -> None:
    parser = argparse.ArgumentParser(description="LongBench v3 no-wiki baseline")
    parser.add_argument("--subsets", default=",".join(SUBSETS))
    parser.add_argument("--max-queries", type=int, default=DEFAULT_MAX_QUERIES)
    parser.add_argument("--pool", type=int, default=50)
    args = parser.parse_args()

    subsets = [item.strip() for item in args.subsets.split(",") if item.strip()]
    missing = [str(_data_path(item)) for item in subsets if not _data_path(item).exists()]
    if missing:
        raise SystemExit(f"Missing LongBench data files: {missing}")
    await ensure_cfg_async()
    doc_map = _require_doc_map()
    mapping = doc_map.get("mapping") or {}
    kb_ids = doc_map.get("kb_ids") or {}

    rows = [attach_v3_gold(row, mapping) for row in load_rows(subsets)]
    if args.max_queries:
        rows = rows[: args.max_queries]
    queries = []
    for row in rows:
        if row["subset"] not in kb_ids:
            continue
        queries.append(
            {
                "qid": row["qid"],
                "question": row["question"],
                "gold_docs": row["answer_gold_docs"],
                "kb": SimpleNamespace(id=uuid.UUID(kb_ids[row["subset"]])),
            }
        )

    if not queries:
        raise SystemExit("No evaluable queries after applying the document map")
    results = await run_eval(queries, queries[0]["kb"], args.pool, use_rerank=True)
    by_qid = {row["qid"]: row for row in rows}
    for result in results:
        row = by_qid.get(result["qid"], {})
        result.update(
            {
                "answer_gold_docs": row.get("answer_gold_docs", []),
                "bridge_gold_docs": row.get("bridge_gold_docs", []),
                "hop_gold_docs": row.get("hop_gold_docs", []),
                "gold_origin": row.get("gold_origin"),
                "question_type": row.get("question_type"),
                "hop_count": row.get("hop_count"),
            }
        )

    meta = {
        "dataset": "zai-org/LongBench five-subset current pipeline",
        "pipeline": "no-wiki hybrid retrieval + rerank",
        "subsets": subsets,
        "pool_size": args.pool,
        "executed_queries": len(results),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    payload = {"meta": meta, "results": results}
    save_json(RESULTS_PATH, payload)
    disclosure = summarize_v3(results, BASE_K_VALUES)
    strict = summarize_v3(results, BASE_K_VALUES, strict_only=True)
    summary = {"meta": meta, "disclosure": disclosure, "strict": strict}
    save_json(SUMMARY_PATH, summary)
    REPORT_PATH.write_text(
        render_v3_report("LongBench v3 no-wiki baseline", meta, disclosure, strict),
        encoding="utf-8",
    )
    print(f"[v3] baseline results: {RESULTS_PATH}")
    print(f"[v3] baseline report: {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())

