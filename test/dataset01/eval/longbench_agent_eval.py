"""Agent-level end-to-end eval (agentic-relation-retrieval, task 4.1/4.2).

Drives the full chat graph (hierarchical tools included) over LongBench
multi-hop subsets; answers judged by contain-match; records tool-call
sequences, rounds and latency.  Control arm via --no-agent-tools (sets
AGENTIC_TOOLS_ENABLED=false before project import).

Usage:
  uv run python longbench_agent_eval.py                     # 全量多跳子集
  uv run python longbench_agent_eval.py --no-agent-tools    # 对照臂
  uv run python longbench_agent_eval.py --max-queries 20    # 冒烟
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid as uuid_mod
from collections import Counter
from pathlib import Path

# --no-agent-tools 必须在项目模块导入前生效（ENV 为惰性单例）
if "--no-agent-tools" in sys.argv:
    os.environ["AGENTIC_TOOLS_ENABLED"] = "false"
    sys.argv.remove("--no-agent-tools")

import common  # noqa: F401  # 注入项目根到 sys.path

from common import RESULTS_DIR, ensure_cfg_async, load_json, save_json
from longbench_eval import DOC_MAP_PATH, load_rows, normalize
from longbench_eval import answer_fragments
from v3 import attach_v3_gold

TIMEOUT = 240
CONCURRENCY = 4
SUBSETS = ["2wikimqa", "hotpotqa", "musique"]
AGENT_TOOLS = {"entity_relation_lookup", "chunk_read"}


def contain_match(prediction: str, answers: list[str]) -> bool:
    pred = normalize(prediction)
    if not pred:
        return False
    for ans in answers or []:
        for frag in answer_fragments(str(ans)):
            if frag and frag in pred:
                return True
    return False


async def run_queries(rows: list[dict], partial_path: Path) -> list[dict]:
    from langchain_core.messages import HumanMessage

    from agent.graph.chat_graph import chat_graph

    graph = chat_graph.get()
    semaphore = asyncio.Semaphore(CONCURRENCY)
    # 断点续跑：逐条追加 JSONL，重启后跳过已完成 qid（防宕机丢失整批结果）
    done_map: dict[str, dict] = {}
    if partial_path.exists():
        with partial_path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    item = json.loads(line)
                    done_map[str(item["qid"])] = item
                except (ValueError, KeyError):
                    continue
    write_lock = asyncio.Lock()

    async def one(row: dict) -> dict:
        async with semaphore:
            started = time.monotonic()
            out = {
                "qid": row["qid"],
                "question": row["question"],
                "answers": row.get("answers") or [],
                "status": "ok",
                "correct": False,
                "answer": "",
                "tool_calls": [],
                "latency_ms": 0.0,
            }
            # 瞬时连接错误重试 1 次（网关抖动高发；仅 ok 结果落盘，
            # failed 留在待办集由续跑/重跑兕底）
            for attempt in range(2):
                out["status"] = "ok"
                out["error"] = ""
                try:
                    async with asyncio.timeout(TIMEOUT):
                        final = await graph.ainvoke(
                            {
                                "messages": [HumanMessage(content=row["question"])],
                                "question": row["question"],
                                "kb_ids": [row["kb_hex"]],
                                "use_web_search": False,
                                "reasoning_effort": None,
                            },
                            config={"configurable": {"thread_id": uuid_mod.uuid4().hex}},
                        )
                    out["answer"] = final.get("answer") or ""
                    calls = list((final.get("metrics") or {}).get("tool_call_names") or [])
                    out["tool_calls"] = calls
                    out["correct"] = contain_match(out["answer"], out["answers"])
                    break
                except TimeoutError:
                    out["status"] = "timeout"
                    if attempt == 0:
                        await asyncio.sleep(3)
                        continue
                except Exception as exc:
                    out["status"] = "failed"
                    out["error"] = f"{type(exc).__name__}: {exc}"[:200]
                    if attempt == 0 and "Connection" in out["error"]:
                        await asyncio.sleep(5)
                        continue
                    break
            out["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
            results_done.append(1)
            if out["status"] == "ok":
                async with write_lock:
                    with partial_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(out, ensure_ascii=False) + "\n")
            print(f"[agent-eval] {len(results_done)} {row['qid'][:40]} {out['status']} correct={out['correct']} {out['latency_ms']:.0f}ms", flush=True)
            return out

    results_done: list[int] = []
    todo = [row for row in rows if str(row["qid"]) not in done_map]
    print(f"[agent-eval] resume: done={len(done_map)} todo={len(todo)}", flush=True)
    fresh = await asyncio.gather(*(one(row) for row in todo))
    return list(done_map.values()) + list(fresh)


def summarize(results: list[dict]) -> dict:
    ok = [r for r in results if r["status"] == "ok"]
    correct = sum(1 for r in ok if r["correct"])
    calls = Counter(name for r in ok for name in r["tool_calls"])
    via_agent_tools = sum(
        1 for r in ok if any(name in AGENT_TOOLS for name in r["tool_calls"])
    )
    via_correct = sum(
        1
        for r in ok
        if r["correct"] and any(name in AGENT_TOOLS for name in r["tool_calls"])
    )
    latency = [r["latency_ms"] for r in ok]
    rounds = [len(r["tool_calls"]) for r in ok]
    return {
        "total": len(results),
        "ok": len(ok),
        "timeout": sum(1 for r in results if r["status"] == "timeout"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "accuracy": round(correct / len(ok), 4) if ok else None,
        "correct": correct,
        "tool_calls": dict(calls.most_common()),
        "avg_tool_rounds": round(sum(rounds) / len(rounds), 2) if rounds else 0,
        "avg_latency_ms": round(sum(latency) / len(latency), 0) if latency else 0,
        "via_agent_tools": via_agent_tools,
        "via_agent_tools_correct": via_correct,
        "agent_tools_enabled": os.environ.get("AGENTIC_TOOLS_ENABLED", "true") != "false",
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-queries", type=int, default=None)
    parser.add_argument("--out", default="longbench_agent_eval_results.json")
    args = parser.parse_args()

    await ensure_cfg_async()
    # 评测独立进程：自行装配 checkpointer（幂等；生产由应用 lifespan 装配）
    from agent.checkpoints.postgres import close_checkpointer, open_checkpointer

    await open_checkpointer()
    doc_map = load_json(DOC_MAP_PATH)
    rows = []
    for subset in SUBSETS:
        kb_hex = (doc_map.get("kb_ids") or {}).get(subset)
        if not kb_hex:
            continue
        for row in load_rows([subset]):
            row = attach_v3_gold(row, {})
            if row.get("question_type") != "multi-hop":
                continue
            row = dict(row)
            row["kb_hex"] = kb_hex
            rows.append(row)
    if args.max_queries:
        rows = rows[: args.max_queries]
    print(f"[agent-eval] rows={len(rows)} agent_tools={os.environ.get('AGENTIC_TOOLS_ENABLED', 'true') != 'false'}", flush=True)
    partial_path = RESULTS_DIR / (args.out + ".partial.jsonl")
    results = await run_queries(rows, partial_path)
    summary = summarize(results)
    save_json(RESULTS_DIR / args.out, {"summary": summary, "results": results})
    print(f"[agent-eval] SUMMARY {summary}", flush=True)
    await close_checkpointer()


if __name__ == "__main__":
    asyncio.run(main())
