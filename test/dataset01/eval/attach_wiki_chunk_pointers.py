"""Attach representative chunk pointers to existing wiki topic pages.

Reads each KB's page set from the wiki collection, anchors one leaf chunk
per member document offline (page-entity anchoring), and upserts the pages
back — no topic regeneration.  Idempotent: rerunning produces the same
pointers.

Usage: uv run python attach_wiki_chunk_pointers.py [--scopes kb1,kb2]
"""

from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, ".")

MUSIQUE_KB = "019ffdecad9d7a53b9da62fbb5791c10"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scopes", default=None, help="comma-separated kb scopes; default all LongBench KBs")
    parser.add_argument("--max-pages", type=int, default=None, help="pilot: only attach to first N pages")
    args = parser.parse_args()

    from common import ensure_cfg_async, load_json
    from longbench_eval import DOC_MAP_PATH

    await ensure_cfg_async()
    doc_map = load_json(DOC_MAP_PATH)
    scopes = (
        [s.strip() for s in args.scopes.split(",") if s.strip()]
        if args.scopes
        else list((doc_map.get("kb_ids") or {}).values())
    )
    print(f"[pointers] scopes: {len(scopes)}")

    from wiki.pointers import attach_chunk_pointers
    from wiki.storage import TopicPageStore

    total_pages = total_with_chunks = total_chunk_ptrs = 0
    for scope in scopes:
        store = TopicPageStore(scope)
        pages = store.list_pages()
        if args.max_pages:
            pages = pages[: args.max_pages]
        before = sum(1 for p in pages if p.chunks)
        if not pages:
            print(f"[pointers] scope={scope[:12]} no pages, skip", flush=True)
            continue
        attached = await attach_chunk_pointers(pages, scope)
        store.upsert_pages(attached)
        with_chunks = sum(1 for p in attached if p.chunks)
        ptrs = sum(len(p.chunks) for p in attached)
        total_pages += len(attached)
        total_with_chunks += with_chunks
        total_chunk_ptrs += ptrs
        print(
            f"[pointers] scope={scope[:12]} pages={len(attached)} "
            f"with_chunks={with_chunks} ptrs={ptrs} (before={before})",
            flush=True,
        )
    print(
        f"[pointers] DONE pages={total_pages} with_chunks={total_with_chunks} "
        f"ptrs={total_chunk_ptrs}"
    )


if __name__ == "__main__":
    asyncio.run(main())
