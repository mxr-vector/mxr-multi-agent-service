"""Smoke tests for hierarchical deterministic tools (task 3.1).

Repo convention: no test framework — run directly:
  uv run python test/dataset01/eval/test_agent_tools_units.py
"""

from __future__ import annotations

import asyncio
import sys

import common  # noqa: F401  # 注入项目根到 sys.path


async def _run() -> int:
    from agent.tools.rag_tools import (
        TOOL_CHUNK_READ,
        TOOL_IMPLS,
        chunk_read_impl,
    )

    failed = 0
    total = 4

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal failed
        if cond:
            print(f"PASS {name}")
        else:
            failed += 1
            print(f"FAIL {name}: {detail}")

    # chunk_read：空 ids 与无效 id 均短路为空
    out = await chunk_read_impl([], None)
    check("chunkread_empty", out.metrics.get("chunks") == 0, out.text)
    out = await chunk_read_impl(["zzz-not-uuid"], None)
    check("chunkread_bad_id", out.metrics.get("chunks") == 0, out.text)

    # TOOL_IMPLS 注册完整
    check(
        "tool_impls_registered",
        TOOL_CHUNK_READ in TOOL_IMPLS,
        str(list(TOOL_IMPLS)),
    )

    # chat 图可导入新工具（绑定链路不抛错）
    from agent.graph.chat_graph import chunk_read  # noqa: F401

    check("chat_graph_import", True)

    print(f"{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
