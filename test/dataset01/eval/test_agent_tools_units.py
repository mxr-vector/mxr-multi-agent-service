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
        TOOL_ENTITY_RELATION_LOOKUP,
        TOOL_IMPLS,
        chunk_read_impl,
        entity_relation_lookup_impl,
    )

    failed = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal failed
        if cond:
            print(f"PASS {name}")
        else:
            failed += 1
            print(f"FAIL {name}: {detail}")

    # 空实体：短路返回空结果（不触库）
    out = await entity_relation_lookup_impl("", ["kb"], None)
    check(
        "relation_empty_entity",
        out.metrics.get("relations") == 0 and "为空" in out.text,
        out.text,
    )

    # 无效库 id：解析后为空 → 无记录路径（不报错）
    out = await entity_relation_lookup_impl("some entity", ["not-a-uuid"], None)
    check("relation_bad_kb", out.metrics.get("relations") == 0, str(out.metrics))

    # chunk_read：空 ids 与无效 id 均短路为空
    out = await chunk_read_impl([], None)
    check("chunkread_empty", out.metrics.get("chunks") == 0, out.text)
    out = await chunk_read_impl(["zzz-not-uuid"], None)
    check("chunkread_bad_id", out.metrics.get("chunks") == 0, out.text)

    # TOOL_IMPLS 注册完整
    check(
        "tool_impls_registered",
        TOOL_ENTITY_RELATION_LOOKUP in TOOL_IMPLS and TOOL_CHUNK_READ in TOOL_IMPLS,
        str(list(TOOL_IMPLS)),
    )

    # chat 图可导入新工具（绑定链路不抛错）
    from agent.graph.chat_graph import chunk_read, entity_relation_lookup  # noqa: F401

    check("chat_graph_import", True)

    print(f"{5 - failed}/5 passed" if failed < 5 else "0/5 passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
