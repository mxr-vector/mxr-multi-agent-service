"""CLI: build entity bridge index for eval knowledge bases (task 2.2/2.3).

Usage:
  uv run python build_entity_index.py                 # doc_map 全部库
  uv run python build_entity_index.py --kb-ids a,b    # 指定库
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from common import ensure_cfg_async, load_json
from longbench_eval import DOC_MAP_PATH


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb-ids", default="", help="逗号分隔；缺省为 doc_map 全部库")
    args = parser.parse_args()

    await ensure_cfg_async()
    from core.config_snapshot import CFG
    from entity_index.builder import build_entity_index

    doc_map = load_json(DOC_MAP_PATH)
    kb_ids_map = doc_map.get("kb_ids") or {}
    if args.kb_ids:
        wanted = {k.strip() for k in args.kb_ids.split(",") if k.strip()}
        kb_ids_map = {
            name: kid
            for name, kid in kb_ids_map.items()
            if kid in wanted or name in wanted
        }
    percent = CFG.entity_generic_df_percent

    for name, kid in kb_ids_map.items():
        stats = await build_entity_index(uuid.UUID(kid), generic_df_percent=percent)
        print(
            f"[entity-index] {name}: docs={stats.documents} entities={stats.entities} "
            f"generic={stats.generic_entities} postings={stats.postings}",
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
