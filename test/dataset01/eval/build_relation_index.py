"""Build entity relation index (agentic-relation-retrieval, tasks 2.2/2.3).

Offline LLM extraction of typed relations + bridge fact sentences from leaf
chunks containing >=2 indexed entities (word-boundary matched), scoped to
documents reachable from eval multi-hop question entities.  Idempotent with
(kb, chunk)-level progress table (resume-safe); concurrency/timeout tunable.

Usage:
  uv run python build_relation_index.py                 # 3 多跳子集全量
  uv run python build_relation_index.py --limit 30      # 冒烟
  uv run python build_relation_index.py --rebuild       # 清空重建
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
import uuid

from common import ensure_cfg_async, load_json
from longbench_eval import DOC_MAP_PATH, load_rows
from v3 import attach_v3_gold

CHUNK_CHARS = 1200
EXTRACT_TIMEOUT = 180.0
PROGRESS_FLUSH = 50

PROMPT = """你是信息抽取助手。给定文本块与其中已索引的实体列表，抽取这些实体之间的直接关系。
严格要求：
1. 输出 JSON 数组（单行紧凑格式，不要换行/缩进），每项形如 {{"head": 实体, "relation": 关系短语, "tail": 实体, "fact": 承载该关系的原文句子}}；
2. relation 用简洁的自由文本（如 father / director of / located in），语言与文本一致；
3. fact 必须是文本块中承载该关系的原句（可截取，不得改写，不超过 200 字符）；
4. 只抽取文本明确陈述的关系，不得推测或虚构；最多 6 条；无关系时输出 []；不输出任何解释文字。
文本块：
{chunk}
已索引实体：{entities}"""


def word_boundary_pattern(entity: str) -> re.Pattern:
    escaped = re.escape(entity)
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE)


def parse_relations(raw: str, chunk_entities: set[str]) -> list[dict]:
    """JSON 数组解析 + 校验（head/tail 须在本块匹配实体中）。"""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        items = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return []
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        head = str(item.get("head") or "").strip().casefold()
        tail = str(item.get("tail") or "").strip().casefold()
        relation = str(item.get("relation") or "").strip()[:256]
        fact = str(item.get("fact") or "").strip()[:1000]
        if not head or not tail or not relation or head == tail:
            continue
        if head not in chunk_entities or tail not in chunk_entities:
            continue
        out.append({"head": head, "tail": tail, "relation": relation, "fact": fact})
    return out


async def reachable_doc_ids(conn, kb_hex: str, subsets_rows: list[dict]) -> set[str]:
    from agent.tools.multihop import extract_english_phrases
    from sqlalchemy import text as sql

    ents: set[str] = set()
    for row in subsets_rows:
        if row.get("question_type") == "multi-hop":
            ents.update(e.casefold() for e in extract_english_phrases(row["question"], 8))
    ents_list = sorted(ents)
    docs: set[str] = set()
    for i in range(0, len(ents_list), 500):
        res = (
            await conn.execute(
                sql(
                    "SELECT DISTINCT document_id FROM rag.entity_index_postings "
                    "WHERE kb_id=:kb AND entity = ANY(:ents)"
                ),
                {"kb": kb_hex, "ents": ents_list[i : i + 500]},
            )
        ).all()
        docs.update(str(r[0]) for r in res)
    return docs


async def build_kb(
    kb_hex: str,
    name: str,
    rows: list[dict],
    *,
    concurrency: int,
    limit: int | None,
    rebuild: bool,
) -> dict:
    from model.chat.factory import build_chat_model
    from sqlalchemy import text as sql
    from core.source.postgres import PostgresConfig
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(PostgresConfig.from_env().async_connection)
    model = build_chat_model(temperature=0, reasoning_effort="off")
    # qwen3 系默认开思考会产出长思维链（单调用 150s+）；抽取任务显式关闭思考，
    # 兼容 OpenAI 兼容参数与 chat_template_kwargs 两种下发方式（无效参数服务端忽略）
    try:
        model.extra_body = {**(model.extra_body or {}), "chat_template_kwargs": {"enable_thinking": False}, "enable_thinking": False}
    except Exception:
        pass
    sem = asyncio.Semaphore(concurrency)
    stats = {"chunks": 0, "eligible": 0, "skipped_done": 0, "relations": 0, "failed": 0}

    async with engine.connect() as conn:
        docs = await reachable_doc_ids(conn, kb_hex, rows)
        if rebuild:
            await conn.execute(sql("DELETE FROM rag.entity_index_relations WHERE kb_id=:kb"), {"kb": kb_hex})
            await conn.execute(sql("DELETE FROM rag.entity_index_extract_progress WHERE kb_id=:kb"), {"kb": kb_hex})
        done = {
            str(r[0])
            for r in (
                await conn.execute(
                    sql(
                        "SELECT chunk_id FROM rag.entity_index_extract_progress "
                        "WHERE kb_id=:kb AND status='done'"
                    ),
                    {"kb": kb_hex},
                )
            ).all()
        }
        doc_list = sorted(docs)
        # 文档实体与叶块（分批拉取，ANY 语法）
        doc_entities: dict[str, list[str]] = {}
        chunk_rows: list = []
        for i in range(0, len(doc_list), 2000):
            batch = doc_list[i : i + 2000]
            post = (
                await conn.execute(
                    sql(
                        "SELECT document_id, entity FROM rag.entity_index_postings "
                        "WHERE kb_id=:kb AND document_id = ANY(:docs)"
                    ),
                    {"kb": kb_hex, "docs": batch},
                )
            ).all()
            for did, e in post:
                doc_entities.setdefault(str(did), []).append(e)
            ch = (
                await conn.execute(
                    sql(
                        "SELECT id, document_id, content FROM rag.rag_chunks "
                        "WHERE document_id = ANY(:docs) AND level=0 "
                        "ORDER BY document_id, chunk_index"
                    ),
                    {"docs": batch},
                )
            ).all()
            chunk_rows.extend(ch)
    print(f"[rel] {name}: reachable_docs={len(doc_list)} chunks={len(chunk_rows)}", flush=True)

    pending = []
    patterns_cache: dict[str, re.Pattern] = {}
    for cid, did, content in chunk_rows:
        cid_hex = str(cid)
        stats["chunks"] += 1
        if cid_hex in done:
            stats["skipped_done"] += 1
            continue
        content_l = (content or "").casefold()
        ents_here = []
        for e in doc_entities.get(str(did), []):
            pat = patterns_cache.get(e)
            if pat is None:
                pat = patterns_cache[e] = word_boundary_pattern(e)
            if pat.search(content_l):
                ents_here.append(e)
        ents_here = sorted(set(ents_here))[:6]
        if len(ents_here) < 2:
            continue
        stats["eligible"] += 1
        pending.append((cid, did, (content or "")[:CHUNK_CHARS], ents_here))
        if limit is not None and len(pending) >= limit:
            break
    print(f"[rel] {name}: eligible={stats['eligible']} skipped_done={stats['skipped_done']}", flush=True)

    async def extract(cid, did, chunk_text, ents):
        async with sem:
            for attempt in range(2):
                t0 = time.monotonic()
                try:
                    resp = await asyncio.wait_for(
                        model.ainvoke(
                            [{"role": "user", "content": PROMPT.format(chunk=chunk_text, entities=", ".join(ents))}]
                        ),
                        timeout=EXTRACT_TIMEOUT,
                    )
                    raw = getattr(resp, "content", None) or str(resp)
                    rels = parse_relations(raw, set(ents))
                    print(f"[rel] CALL_OK chunk={str(cid)[:12]} {time.monotonic()-t0:.1f}s rels={len(rels)}", flush=True)
                    return ("done", rels)
                except Exception as exc:
                    if attempt == 1:
                        print(f"[rel] EXTRACT_FAIL chunk={str(cid)[:12]} {time.monotonic()-t0:.1f}s {type(exc).__name__}: {str(exc)[:120]}", flush=True)
                        return ("failed", [])
                    await asyncio.sleep(2)

    from sqlalchemy import text as sql

    flush_rels: list[dict] = []
    flush_prog: list[tuple] = []

    async def flush(engine):
        nonlocal flush_rels, flush_prog
        if not flush_rels and not flush_prog:
            return
        async with engine.begin() as conn:
            if flush_rels:
                await conn.execute(
                    sql(
                        "INSERT INTO rag.entity_index_relations "
                        "(kb_id, head_entity, tail_entity, relation, fact_text, chunk_id, document_id) "
                        "VALUES (:kb, :head, :tail, :rel, :fact, :chunk, :doc)"
                    ),
                    flush_rels,
                )
            if flush_prog:
                await conn.execute(
                    sql(
                        "INSERT INTO rag.entity_index_extract_progress (kb_id, chunk_id, status, updated_at) "
                        "VALUES (:kb, :chunk, :status, now()) "
                        "ON CONFLICT (kb_id, chunk_id) DO UPDATE SET status=EXCLUDED.status, updated_at=now()"
                    ),
                    flush_prog,
                )
        flush_rels, flush_prog = [], []

    t0 = time.monotonic()
    for i in range(0, len(pending), concurrency * 2):
        batch = pending[i : i + concurrency * 2]
        results = await asyncio.gather(*(extract(*item) for item in batch))
        for (cid, did, _chunk, _ents), (status, rels) in zip(batch, results):
            flush_prog.append({"kb": kb_hex, "chunk": cid, "status": status})
            if status == "failed":
                stats["failed"] += 1
                continue
            for rel in rels:
                flush_rels.append(
                    {
                        "kb": kb_hex,
                        "head": rel["head"],
                        "tail": rel["tail"],
                        "rel": rel["relation"],
                        "fact": rel["fact"],
                        "chunk": cid,
                        "doc": did,
                    }
                )
                stats["relations"] += 1
            if len(flush_prog) >= PROGRESS_FLUSH:
                await flush(engine)
        if (i // (concurrency * 2)) % 10 == 0:
            rate = (i + len(batch)) / max(1e-6, time.monotonic() - t0)
            print(
                f"[rel] {name}: {i + len(batch)}/{len(pending)} "
                f"relations={stats['relations']} failed={stats['failed']} rate={rate:.1f}/s",
                flush=True,
            )
    await flush(engine)
    await engine.dispose()
    stats["elapsed_s"] = round(time.monotonic() - t0, 1)
    print(f"[rel] {name}: DONE {stats}", flush=True)
    return stats


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subsets", default="2wikimqa,hotpotqa,musique")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    await ensure_cfg_async()
    # 确保表存在
    from entity.base import Base
    from entity.rag.entity_index import EntityIndexRelation, EntityIndexExtractProgress
    from core.source.postgres import PostgresConfig
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(PostgresConfig.from_env().async_connection)
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[EntityIndexRelation.__table__, EntityIndexExtractProgress.__table__],
            )
        )
    await engine.dispose()

    doc_map = load_json(DOC_MAP_PATH)
    for name in [s.strip() for s in args.subsets.split(",") if s.strip()]:
        kb = doc_map["kb_ids"][name]
        rows = [attach_v3_gold(r, {}) for r in load_rows([name])]
        await build_kb(
            kb, name, rows,
            concurrency=args.concurrency, limit=args.limit, rebuild=args.rebuild,
        )


if __name__ == "__main__":
    asyncio.run(main())
