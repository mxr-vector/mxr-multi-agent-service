"""Offline entity bridge index builder (design D1/D4/D5).

Idempotent per-KB full rebuild: extract entities from every active document
(title as the highest-weight source, then a content prefix), accumulate the
inverted postings, compute doc_freq, and mark generic entities by the
statistical criterion ``doc_freq / kb_doc_count > threshold`` (no
vocabularies).  Online query paths never call this module.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from string import Template
from typing import AsyncIterator

from sqlalchemy import text

from entity_index.extractors import get_extractor

# 单文档参与抽取的正文前缀长度（标题已提供主实体，正文前缀补足共现信号）
DEFAULT_CONTENT_CHARS = 2000
# 单实体串入库长度上限（列宽 256，留余量）
MAX_ENTITY_LEN = 255
# postings 批量写入大小
POSTING_BATCH = 5000


@dataclass(frozen=True)
class BuildStats:
    kb_id: str
    documents: int
    entities: int
    generic_entities: int
    postings: int


async def build_entity_index(
    kb_id: uuid.UUID,
    *,
    generic_df_percent: int,
    extractor_name: str = "rule_v1",
    content_chars: int = DEFAULT_CONTENT_CHARS,
) -> BuildStats:
    """Rebuild the entity index for one knowledge base (idempotent)."""
    from core.source.postgres import PostgresConfig
    from sqlalchemy.ext.asyncio import create_async_engine

    extractor = get_extractor(extractor_name)
    engine = create_async_engine(PostgresConfig.from_env().async_connection)

    # 实体 -> 文档集合（内存累积；评测库规模 10 万级文档可承载）
    entity_docs: dict[str, set[uuid.UUID]] = defaultdict(set)
    doc_count = 0

    try:
        async with engine.connect() as conn:
            stream: AsyncIterator = await conn.stream(
                text(
                    "SELECT id, title, left(content, :n) AS body "
                    "FROM rag.rag_documents "
                    "WHERE knowledge_base_id = :kb AND status = 'active'"
                ),
                {"kb": kb_id, "n": content_chars},
            )
            async for row in stream:
                doc_count += 1
                entities: set[str] = set()
                if row.title:
                    entities |= extractor.extract(str(row.title))
                if row.body:
                    entities |= extractor.extract(str(row.body))
                for entity in entities:
                    entity = entity[:MAX_ENTITY_LEN]
                    if entity:
                        entity_docs[entity].add(row.id)
        if doc_count == 0:
            raise ValueError(f"knowledge base {kb_id} has no active documents")

        threshold = max(1, int(doc_count * generic_df_percent / 100))

        async with engine.begin() as conn:
            # 幂等覆盖：先清空该 kb 既有索引行
            await conn.execute(
                text("DELETE FROM rag.entity_index_postings WHERE kb_id = :kb"),
                {"kb": kb_id},
            )
            await conn.execute(
                text("DELETE FROM rag.entity_index_entities WHERE kb_id = :kb"),
                {"kb": kb_id},
            )

            entity_rows = []
            posting_rows = []
            generic_count = 0
            for entity, docs in entity_docs.items():
                doc_freq = len(docs)
                is_generic = doc_freq > threshold
                if is_generic:
                    generic_count += 1
                entity_rows.append((kb_id, entity, doc_freq, is_generic))
                for doc_id in docs:
                    posting_rows.append((kb_id, entity, doc_id))

            for start in range(0, len(entity_rows), POSTING_BATCH):
                await conn.execute(
                    text(
                        "INSERT INTO rag.entity_index_entities "
                        "(kb_id, entity, doc_freq, is_generic) "
                        "VALUES (:kb, :entity, :df, :generic)"
                    ),
                    [
                        {"kb": kb_id, "entity": e, "df": df, "generic": g}
                        for (kb_id, e, df, g) in entity_rows[
                            start : start + POSTING_BATCH
                        ]
                    ],
                )
            for start in range(0, len(posting_rows), POSTING_BATCH):
                await conn.execute(
                    text(
                        "INSERT INTO rag.entity_index_postings "
                        "(kb_id, entity, document_id) "
                        "VALUES (:kb, :entity, :doc)"
                    ),
                    [
                        {"kb": kb_id, "entity": e, "doc": d}
                        for (kb_id, e, d) in posting_rows[start : start + POSTING_BATCH]
                    ],
                )

        return BuildStats(
            kb_id=kb_id.hex,
            documents=doc_count,
            entities=len(entity_docs),
            generic_entities=generic_count,
            postings=len(posting_rows),
        )
    finally:
        await engine.dispose()
        # 重建后立即失效进程内缓存，避免在线路径读到旧索引
        try:
            from entity_index.store import invalidate_entity_bundle

            invalidate_entity_bundle(kb_id.hex)
        except Exception:
            pass


# ---------- 关系索引（生产级：全量范围 + 断点续建） ----------
# 用 string.Template 注入不可信文档内容：str.format 对含花括号的文本块（JSON/代码/
# 模板文本）会抛 KeyError/ValueError，导致该类块被永久标记 failed。
RELATION_PROMPT = Template(
    """你是信息抽取助手。给定文本块与其中已索引的实体列表，抽取这些实体之间的直接关系。
严格要求：
1. 输出 JSON 数组（单行紧凑格式），每项形如 {"head": 实体, "relation": 关系短语, "tail": 实体, "fact": 承载该关系的原文句子}；
2. relation 用简洁自由文本（如 父亲 / 导演 / 位于），语言与文本一致；
3. fact 必须是文本块中承载该关系的原句（可截取，不得改写，不超过 200 字符）；
4. 只抽取文本明确陈述的关系，不得推测或虚构；最多 6 条；无关系时输出 []；不输出任何解释文字。
文本块：
$chunk
已索引实体：$entities"""
)

# 关系抽取参数（实测档位：关思考 + 并发 8 + 180s 超时 ≈ 2,200 块/小时）
RELATION_CONCURRENCY = 8
RELATION_EXTRACT_TIMEOUT = 180.0
RELATION_CHUNK_CHARS = 1200
DOC_BATCH = 2000
PROGRESS_FLUSH = 50


def _word_boundary_pattern(entity: str) -> re.Pattern:
    escaped = re.escape(entity)
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE)


def _parse_relations(raw: str, chunk_entities: set[str]) -> list[dict]:
    """JSON 数组解析 + 校验（head/tail 须在本块匹配实体中）。"""
    txt = (raw or "").strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-zA-Z]*\s*", "", txt)
        txt = re.sub(r"\s*```$", "", txt).strip()
    start, end = txt.find("["), txt.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        items = json.loads(txt[start : end + 1])
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


@dataclass(frozen=True)
class RelationBuildStats:
    kb_id: str
    chunks: int
    eligible: int
    skipped_done: int
    relations: int
    failed: int


async def _probe_thinking_disable(model) -> bool:
    """探测网关是否接受关思考参数（不支持则返回 False，调用方去掉参数）。"""
    try:
        await asyncio.wait_for(
            model.ainvoke(
                [{"role": "user", "content": "ok"}],
                extra_body={
                    "chat_template_kwargs": {"enable_thinking": False},
                    "enable_thinking": False,
                },
            ),
            timeout=30,
        )
        return True
    except Exception:
        return False


async def build_relations(
    kb_id: uuid.UUID,
    *,
    concurrency: int = RELATION_CONCURRENCY,
    extract_timeout: float = RELATION_EXTRACT_TIMEOUT,
    rebuild: bool = False,
) -> RelationBuildStats:
    """对知识库全量范围抽取关系（断点续建，幂等重跑跳过 done 块）。

    前置：实体索引（entity_index_entities/postings）已构建（本函数会校验，
    未构建时报错提示先跑 build_entity_index）。严格使用 DB chat 角色，
    无回退模型策略；失败块记 failed，重跑时自动重试。
    rebuild=True 时先清空该库既有关系记录与进度行再全量重建（文档更新/重分块后用）。
    """
    from core.source.postgres import PostgresConfig
    from model.chat.factory import build_chat_model
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(PostgresConfig.from_env().async_connection)
    model = build_chat_model(temperature=0, reasoning_effort="off")
    # 思考型模型（qwen3 系）需关思考防思维链膨胀；部分网关拒绝未知字段，
    # 故先探测：支持则保留参数，拒绝则自动去掉（自适应，无硬编码）
    thinking_params_ok = await _probe_thinking_disable(model)
    sem = asyncio.Semaphore(concurrency)
    stats = {"chunks": 0, "eligible": 0, "skipped_done": 0, "relations": 0, "failed": 0}
    pattern_cache: dict[str, re.Pattern] = {}

    try:
        async with engine.connect() as conn:
            ent_cnt = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM rag.entity_index_entities WHERE kb_id=:kb"
                    ),
                    {"kb": kb_id},
                )
            ).scalar()
            if not ent_cnt:
                raise RuntimeError(
                    f"kb {kb_id.hex} 实体索引未构建，请先运行 build_entity_index"
                )
        if rebuild:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM rag.entity_index_relations WHERE kb_id=:kb"),
                    {"kb": kb_id},
                )
                await conn.execute(
                    text(
                        "DELETE FROM rag.entity_index_extract_progress WHERE kb_id=:kb"
                    ),
                    {"kb": kb_id},
                )
            print(f"[rel] 重建：已清空 {kb_id.hex} 的关系记录与进度行", flush=True)
        async with engine.connect() as conn:
            done_ids = {
                str(r[0])
                for r in (
                    await conn.execute(
                        text(
                            "SELECT chunk_id FROM rag.entity_index_extract_progress "
                            "WHERE kb_id=:kb AND status='done'"
                        ),
                        {"kb": kb_id},
                    )
                ).all()
            }
            doc_ids = [
                str(r[0])
                for r in (
                    await conn.execute(
                        text(
                            "SELECT id FROM rag.rag_documents "
                            "WHERE knowledge_base_id=:kb AND status='active'"
                        ),
                        {"kb": kb_id},
                    )
                ).all()
            ]

            async def extract(cid, did, chunk_text, ents):
                async with sem:
                    for attempt in range(2):
                        t0 = time.monotonic()
                        try:
                            kwargs = {}
                            if thinking_params_ok:
                                kwargs["extra_body"] = {
                                    "chat_template_kwargs": {"enable_thinking": False},
                                    "enable_thinking": False,
                                }
                            resp = await asyncio.wait_for(
                                model.ainvoke(
                                    [
                                        {
                                            "role": "user",
                                            "content": RELATION_PROMPT.substitute(
                                                chunk=chunk_text,
                                                entities=", ".join(ents),
                                            ),
                                        }
                                    ],
                                    **kwargs,
                                ),
                                timeout=extract_timeout,
                            )
                            raw = getattr(resp, "content", None) or str(resp)
                            rels = _parse_relations(raw, set(ents))
                            print(
                                f"[rel] CALL_OK chunk={str(cid)[:12]} {time.monotonic()-t0:.1f}s rels={len(rels)}",
                                flush=True,
                            )
                            return ("done", rels)
                        except Exception as exc:
                            if attempt == 1:
                                print(
                                    f"[rel] EXTRACT_FAIL chunk={str(cid)[:12]} {time.monotonic()-t0:.1f}s {type(exc).__name__}: {str(exc)[:120]}",
                                    flush=True,
                                )
                                return ("failed", [])
                            await asyncio.sleep(2)

            flush_rels: list[dict] = []
            flush_prog: list[dict] = []

            async def flush():
                nonlocal flush_rels, flush_prog
                if not flush_rels and not flush_prog:
                    return
                async with engine.begin() as conn2:
                    if flush_rels:
                        await conn2.execute(
                            text(
                                "INSERT INTO rag.entity_index_relations "
                                "(kb_id, head_entity, tail_entity, relation, fact_text, chunk_id, document_id) "
                                "VALUES (:kb, :head, :tail, :rel, :fact, :chunk, :doc)"
                            ),
                            flush_rels,
                        )
                    if flush_prog:
                        await conn2.execute(
                            text(
                                "INSERT INTO rag.entity_index_extract_progress (kb_id, chunk_id, status, updated_at) "
                                "VALUES (:kb, :chunk, :status, now()) "
                                "ON CONFLICT (kb_id, chunk_id) DO UPDATE SET status=EXCLUDED.status, updated_at=now()"
                            ),
                            flush_prog,
                        )
                flush_rels, flush_prog = [], []

            for batch_start in range(0, len(doc_ids), DOC_BATCH):
                batch_docs = doc_ids[batch_start : batch_start + DOC_BATCH]
                post = (
                    await conn.execute(
                        text(
                            "SELECT document_id, entity FROM rag.entity_index_postings "
                            "WHERE kb_id=:kb AND document_id = ANY(:docs)"
                        ),
                        {"kb": kb_id, "docs": batch_docs},
                    )
                ).all()
                doc_ents: dict[str, list[str]] = {}
                for did, e in post:
                    doc_ents.setdefault(str(did), []).append(e)
                chunks = (
                    await conn.execute(
                        text(
                            "SELECT id, document_id, content FROM rag.rag_chunks "
                            "WHERE document_id = ANY(:docs) AND level=0 "
                            "ORDER BY document_id, chunk_index"
                        ),
                        {"docs": batch_docs},
                    )
                ).all()
                pending = []
                for cid, did, content in chunks:
                    stats["chunks"] += 1
                    cid_hex = str(cid)
                    if cid_hex in done_ids:
                        stats["skipped_done"] += 1
                        continue
                    ents_here = []
                    content_l = (content or "").casefold()
                    for e in doc_ents.get(str(did), []):
                        pat = pattern_cache.get(e)
                        if pat is None:
                            pat = pattern_cache[e] = _word_boundary_pattern(e)
                        if pat.search(content_l):
                            ents_here.append(e)
                    ents_here = sorted(set(ents_here))[:6]
                    if len(ents_here) < 2:
                        continue
                    stats["eligible"] += 1
                    pending.append(
                        (cid, did, (content or "")[:RELATION_CHUNK_CHARS], ents_here)
                    )
                results = await asyncio.gather(*(extract(*item) for item in pending))
                for (cid, did, _chunk, _ents), (status, rels) in zip(pending, results):
                    flush_prog.append({"kb": kb_id, "chunk": cid, "status": status})
                    if status == "failed":
                        stats["failed"] += 1
                        continue
                    for rel in rels:
                        flush_rels.append(
                            {
                                "kb": kb_id,
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
                        await flush()
            await flush()

        return RelationBuildStats(
            kb_id=kb_id.hex,
            chunks=stats["chunks"],
            eligible=stats["eligible"],
            skipped_done=stats["skipped_done"],
            relations=stats["relations"],
            failed=stats["failed"],
        )
    finally:
        await engine.dispose()
