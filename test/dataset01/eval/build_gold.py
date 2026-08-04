"""
S2 gold 基准表 + 分层抽样：为数据集每条记录生成双口径 gold 并落盘。

- 严格口径（chunk 级）：叶块文本规范化后包含该条 content（句子级匹配；
  content 超过叶块上限时反向判定 chunk ⊂ content）
- 宽松口径（文档级）：同 pageid 聚合文档的全部叶块（pageid → document_id）
- 抽样：按 pageid 分层均衡抽取 sample_size 条（默认 1000，种子 42）

产物：gold/gold_strict.json、gold/gold_relaxed.json、gold/sample_queries.json

用法：
  uv run python test/dataset01/eval/build_gold.py [--seed 42] [--sample-size 1000]
"""

import argparse
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from common import (
    DEFAULT_SAMPLE_SIZE,
    DEFAULT_SEED,
    GOLD_RELAXED_PATH,
    GOLD_STRICT_PATH,
    SAMPLE_QUERIES_PATH,
    ensure_dirs,
    load_dataset,
    normalize,
    save_json,
    stratified_sample,
)

# content 超过该长度（字符）时采用反向包含判定（chunk ⊂ content）
REVERSE_MATCH_THRESHOLD = 400


async def load_corpus_chunks(session, kb_id) -> tuple[dict, dict]:
    """读取评测库全部文档与叶块。

    返回 (pageid_to_doc, pageid_to_chunks)：
    - pageid_to_doc: {pageid: document_id hex}
    - pageid_to_chunks: {pageid: [(chunk_id hex, norm_text)]}
    """
    from entity.rag.chunks import Chunk
    from entity.rag.document import Document

    docs = (
        await session.execute(
            select(Document.id, Document.source_uri).where(
                Document.knowledge_base_id == kb_id
            )
        )
    ).all()
    pageid_to_doc: dict[str, str] = {}
    doc_ids = []
    for doc_id, source_uri in docs:
        if source_uri and source_uri.startswith("wiki:"):
            pageid_to_doc[source_uri[len("wiki:"):]] = doc_id.hex
        doc_ids.append(doc_id)

    chunks = (
        await session.execute(
            select(Chunk.id, Chunk.content, Chunk.document_id)
            .where(Chunk.document_id.in_(doc_ids))
            .where(Chunk.level == 0)
        )
    ).all()
    pageid_to_chunks: dict[str, list[tuple[str, str]]] = {}
    for chunk_id, content, document_id in chunks:
        pageid = next(
            (p for p, d in pageid_to_doc.items() if d == document_id.hex), None
        )
        if pageid is None:
            continue
        pageid_to_chunks.setdefault(pageid, []).append((chunk_id.hex, normalize(content)))
    return pageid_to_doc, pageid_to_chunks


def match_gold_chunks(norm_content: str, page_chunks: list[tuple[str, str]]) -> list[str]:
    """单条 content 的严格 gold：在该页叶块内做规范化包含判定。"""
    if not norm_content or not page_chunks:
        return []
    if len(norm_content) > REVERSE_MATCH_THRESHOLD:
        # 长句反向兜底：chunk ⊂ content（极端长句被切块边界截断场景）
        return [
            chunk_id
            for chunk_id, norm_chunk in page_chunks
            if norm_chunk and norm_chunk in norm_content
        ]
    return [
        chunk_id
        for chunk_id, norm_chunk in page_chunks
        if norm_chunk and norm_content in norm_chunk
    ]


async def build_gold(seed: int, sample_size: int, limit: int | None = None) -> None:
    from database.postgre_client import get_session

    from build_corpus import find_eval_kb

    ensure_dirs()
    df = load_dataset(limit=limit)

    async with get_session() as session:
        kb = await find_eval_kb(session)
        if kb is None:
            raise SystemExit(
                "评测知识库不存在：请先运行 build_corpus.py 建库"
            )
        pageid_to_doc, pageid_to_chunks = await load_corpus_chunks(session, kb.id)

    # 页面级粗筛文本（与聚合文档同构：\n 连接 + 规范化），从原始记录重建
    page_text_buf: dict[str, list[str]] = {}
    for row in df.itertuples():
        page_text_buf.setdefault(str(row.pageid), []).append(str(row.content or ""))
    pageid_to_text = {p: normalize("\n".join(v)) for p, v in page_text_buf.items()}

    strict_gold: dict[str, list[str]] = {}
    relaxed_gold: dict[str, list[str]] = {}
    empty_count = 0
    multi_count = 0
    total = 0
    unmatched_pages = 0

    for row in df.itertuples():
        pageid = str(row.pageid)
        row_index = str(row.Index)
        doc_id = pageid_to_doc.get(pageid)
        norm_content = normalize(row.content)
        total += 1

        if norm_content and pageid in pageid_to_text and norm_content in pageid_to_text[pageid]:
            # 粗筛通过（content 确实出现在页面聚合文本中）→ 逐叶块细化
            gold_chunks = match_gold_chunks(
                norm_content, pageid_to_chunks.get(pageid, [])
            )
        else:
            gold_chunks = []
            if pageid not in pageid_to_doc:
                unmatched_pages += 1

        strict_gold[row_index] = gold_chunks
        if not gold_chunks:
            empty_count += 1
        elif len(gold_chunks) > 1:
            multi_count += 1
        relaxed_gold[row_index] = [doc_id] if doc_id else []

    if limit is not None:
        # 限定子集：直接取前 limit 条记录作为测试集（不复现性抽样）
        sampled = [
            {
                "row_index": row.Index,
                "pageid": str(row.pageid),
                "title": str(row.title or ""),
                "question": str(row.question or ""),
                "content": str(row.content or ""),
            }
            for row in df.itertuples()
        ]
    else:
        sampled = stratified_sample(df, seed=seed, size=sample_size)

    meta = {
        "kb_id": kb.id.hex,
        "seed": seed,
        "sample_size": sample_size,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "records": total,
        "strict_empty_ratio": round(empty_count / total, 4) if total else 0.0,
        "strict_multi_ratio": round(multi_count / total, 4) if total else 0.0,
        "unmatched_pages": unmatched_pages,
    }

    save_json(GOLD_STRICT_PATH, {"meta": meta, "gold": strict_gold})
    save_json(GOLD_RELAXED_PATH, {"meta": meta, "gold": relaxed_gold})
    save_json(
        SAMPLE_QUERIES_PATH,
        {
            "meta": meta,
            "queries": [
                {
                    "row_index": item["row_index"],
                    "pageid": item["pageid"],
                    "title": item["title"],
                    "question": item["question"],
                    "content": item["content"],
                }
                for item in sampled
            ],
        },
    )

    print(
        f"[S2] gold 基准表完成：{total} 条记录，严格口径空占比 {meta['strict_empty_ratio']:.1%}，"
        f"多 gold 占比 {meta['strict_multi_ratio']:.1%}，未匹配页面 {unmatched_pages}"
    )
    print(f"     抽样 {len(sampled)} 条（seed={seed}），已落盘 gold/ 目录")


async def main() -> None:
    parser = argparse.ArgumentParser(description="S2 gold 基准表 + 分层抽样")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="抽样随机种子")
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE, help="采样条数")
    parser.add_argument("--limit", type=int, default=None, help="仅处理前 N 条记录（取前 N 条为测试集，不抽样）")
    args = parser.parse_args()
    await build_gold(args.seed, args.sample_size, args.limit)


if __name__ == "__main__":
    asyncio.run(main())
