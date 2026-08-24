"""Regenerate degraded (fallback) topic pages for one wiki scope.

Only touches pages whose title/summary matches the offline fallback pattern;
clustering and healthy pages stay untouched.  Regenerated pages overwrite the
existing points via the same topic_id.
"""

from __future__ import annotations

import argparse
import asyncio

MUSIQUE_KB = "019ffdecad9d7a53b9da62fbb5791c10"


def is_fallback(page) -> bool:
    return page.title.startswith("lb:") or page.summary.startswith("Navigation index for")


async def build_repair_generator():
    """Generator strictly honoring the DB-configured chat model (no fallback).

    Probes the configured model once; if unavailable, abort loudly instead of
    silently substituting another model.
    """
    from core.config_snapshot import CFG
    from model.chat.factory import build_chat_model

    model = build_chat_model(temperature=0)
    configured = CFG.chat.model_name
    await asyncio.wait_for(model.ainvoke([{"role": "user", "content": "OK"}]), timeout=60)
    print(f"[repair] using configured model: {configured}", flush=True)

    from wiki.generator import _parse_json_object

    async def generator(prompt: str):
        response = await model.ainvoke([{"role": "user", "content": prompt}])
        return _parse_json_object(str(getattr(response, "content", response))) or {}

    return generator


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", default=MUSIQUE_KB)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--max-passes", type=int, default=3)
    args = parser.parse_args()

    from common import ensure_cfg_async

    await ensure_cfg_async()
    from longbench_wiki_pilot import load_documents
    from wiki.storage import TopicPageStore

    store = TopicPageStore(args.scope)
    pages = store.list_pages()
    degraded = [page for page in pages if is_fallback(page)]
    print(f"[repair] scope={args.scope} total={len(pages)} degraded={len(degraded)}")
    if not degraded:
        return

    needed = {doc_id for page in degraded for doc_id in page.documents}
    documents = await load_documents([args.scope])
    doc_map = {doc.document_id: doc for doc in documents if doc.document_id in needed}
    print(f"[repair] loaded {len(documents)} docs, matched {len(doc_map)}/{len(needed)} ids")
    generator = await build_repair_generator()

    for pass_index in range(1, max(1, args.max_passes) + 1):
        repaired, still_fallback = await regenerate_pass(
            degraded, doc_map, store, args.concurrency, generator
        )
        print(f"[repair] pass={pass_index} upserted {len(degraded)} pages, "
              f"repaired={repaired}, still_fallback={still_fallback}")
        if still_fallback == 0:
            break
        degraded = [page for page in store.list_pages() if is_fallback(page)]
        if not degraded:
            break


async def regenerate_pass(degraded, doc_map, store, concurrency, generator=None):
    from wiki.clustering import TopicCluster
    from wiki.generator import generate_topic_page
    from wiki.vectors import DocumentVector

    semaphore = asyncio.Semaphore(max(1, concurrency))
    still_fallback = 0

    async def one(page):
        nonlocal still_fallback
        vectors = [
            DocumentVector(document=doc_map[doc_id], text=doc_map[doc_id].title or doc_id, vector=())
            for doc_id in page.documents
            if doc_id in doc_map
        ]
        if not vectors:
            return page
        cluster = TopicCluster(
            cluster_id=page.topic_id,
            coarse_partition=page.coarse_partition or "repair",
            document_vectors=vectors,
        )
        async with semaphore:
            fresh = await generate_topic_page(
                cluster, version=page.version, related_topics=page.related_topics,
                generator=generator,
            )
        if is_fallback(fresh):
            still_fallback += 1
        return fresh

    results = list(await asyncio.gather(*(one(page) for page in degraded)))
    store.upsert_pages(results, recreate=False)
    repaired = sum(1 for page in results if not is_fallback(page))
    return repaired, still_fallback


if __name__ == "__main__":
    asyncio.run(main())
