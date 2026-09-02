"""Production CLI: build entity index + relation index for knowledge bases.

Usage:
  uv run python -m entity_index.build_cli --kb-id <kb-hex>     # 单库
  uv run python -m entity_index.build_cli --all                # 全部 active 库（单库失败不阻断其余）
  uv run python -m entity_index.build_cli --kb-id <kb-hex> --relations-only
  uv run python -m entity_index.build_cli --kb-id <kb-hex> --relations-only --rebuild  # 清空重建（文档更新后）

步骤：实体索引（倒排+统计判据）→ 关系索引（实体锚定事实句，断点续建）。
模型严格使用 DB chat 角色，无回退模型策略；中断后重跑自动续建。
"""

from __future__ import annotations

import argparse
import asyncio
import uuid


async def build_kb(kb_id: uuid.UUID, relations_only: bool, rebuild: bool) -> None:
    from core.config_snapshot import CFG
    from entity_index.builder import build_entity_index, build_relations

    if not relations_only:
        stats = await build_entity_index(
            kb_id, generic_df_percent=CFG.entity_generic_df_percent
        )
        print(
            f"[entity-index] {kb_id.hex}: docs={stats.documents} "
            f"entities={stats.entities} generic={stats.generic_entities} "
            f"postings={stats.postings}",
            flush=True,
        )
    rel = await build_relations(kb_id, rebuild=rebuild)
    print(
        f"[relation-index] {kb_id.hex}: chunks={rel.chunks} eligible={rel.eligible} "
        f"skipped={rel.skipped_done} relations={rel.relations} failed={rel.failed}",
        flush=True,
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb-id", default=None, help="知识库 id（hex 无连字符亦可）")
    parser.add_argument("--all", action="store_true", help="全部 active 知识库")
    parser.add_argument(
        "--relations-only", action="store_true", help="跳过实体索引，仅建关系"
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="先清空该库既有关系记录与进度行再全量重建（文档更新/重分块后用）",
    )
    args = parser.parse_args()

    from core.config_snapshot import CFG

    await CFG.load()

    from sqlalchemy import text
    from core.source.postgres import PostgresConfig
    from sqlalchemy.ext.asyncio import create_async_engine

    if args.all:
        engine = create_async_engine(PostgresConfig.from_env().async_connection)
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("SELECT id FROM rag.rag_knowledge_bases WHERE status='active'")
                )
            ).all()
        await engine.dispose()
        kb_ids = [r[0] for r in rows]
    elif args.kb_id:
        kb_ids = [uuid.UUID(args.kb_id.replace("-", ""))]
    else:
        raise SystemExit("请指定 --kb-id 或 --all")

    # 批量模式下单库失败隔离：打印 [SKIP] 后继续其余库，不阻断批量任务
    failed_kbs = 0
    for kb_id in kb_ids:
        try:
            await build_kb(kb_id, args.relations_only, args.rebuild)
        except Exception as exc:
            failed_kbs += 1
            print(f"[SKIP] {kb_id.hex}: {type(exc).__name__}: {exc}", flush=True)
    if failed_kbs:
        raise SystemExit(f"{failed_kbs} 个知识库构建失败，其余已完成")


if __name__ == "__main__":
    asyncio.run(main())
