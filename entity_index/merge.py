"""Merge entity-expansion candidates into the multihop final ranking (design D3).

Expansion hits are document-level; the final rerank needs chunk text.  The
online wiring fetches entity-anchored leaf chunks from PG (co-occurrence
candidates) plus wiki chunk-pointer hits (by id) and passes them here.
``expansion_hop_result`` wraps them as a labeled hop result for the merge
pool; ``merge_final_with_expansion`` then injects the expansion channel's
own-query rerank winners into reserved final seats — the unified final
rerank over the original question stays untouched for the main path.
"""

from __future__ import annotations

from typing import Sequence

from agent.tools.multihop import HopResult

# 扩展通道进入合并池的候选总量上限（cap C），防止挤占逐跳候选
DEFAULT_EXPANSION_CAP_C = 15

# 扩展通道在终排结果中的保留席位数：桥接证据回答的是中间实体而非原
# 问题，按原问题统一重排会结构性淘汰它们，因此扩展通道用自身查询独立
# 重排后按席位注入终排尾部（0 关闭注入）。quota 扫描实测（1000 条生产
# 语义臂）：2→3→4→5 bridge@10 0.128/0.133/0.135/0.137 单调升、hop@10
# 于 4 席走平，5 席后增益边际化收敛；单跳/跨文档题型全程不受影响
EXPANSION_FINAL_QUOTA = 5

# 扩展通道在 hop_coverage 中的跳标签（区别于逐跳的 0/1）
EXPANSION_HOP_LABEL = 2


def expansion_hop_result(
    chunks: Sequence[dict],
    *,
    cap_c: int = DEFAULT_EXPANSION_CAP_C,
    hop: int = EXPANSION_HOP_LABEL,
) -> HopResult | None:
    """Wrap fetched expansion chunks as a hop result for collect_hop_pool.

    Each chunk must carry document_id/text (as returned by the document
    fetch step).  Returns None when there are no chunks so callers can skip
    the channel entirely (graceful degradation).
    """
    docs = []
    seen: set[str] = set()
    for chunk in chunks:
        doc_id = str(chunk.get("document_id") or "")
        if not chunk.get("text") or (doc_id and doc_id in seen):
            continue
        if doc_id:
            seen.add(doc_id)
        docs.append({**chunk, "score": 0.0})
        if len(docs) >= cap_c:
            break
    if not docs:
        return None
    return HopResult(hop=hop, query="<entity-expansion>", docs=docs)


def merge_final_with_expansion(
    main_docs: Sequence[dict],
    expansion_docs: Sequence[dict],
    quota: int = EXPANSION_FINAL_QUOTA,
) -> tuple[list[dict], int]:
    """Reserve final-top-k tail seats for entity-expansion evidence.

    Both inputs are already reranked (main by the original question, expansion
    by its own entity-focused query); their scores are computed against
    different queries and MUST NOT be compared, so expansion winners are
    appended after the main docs instead of interleaved.  Documents already
    present in the main list are skipped; fewer seats may be filled when the
    expansion channel runs dry.  Returns (final docs, seats actually filled).
    """
    if quota <= 0 or not expansion_docs:
        return list(main_docs), 0
    final = list(main_docs)
    present = {str(doc.get("document_id") or "") for doc in final}
    filled = 0
    for doc in expansion_docs:
        if filled >= quota:
            break
        if str(doc.get("document_id") or "") in present:
            continue
        entry = dict(doc)
        entry.setdefault("source_hops", []).append(EXPANSION_HOP_LABEL)
        final.append(entry)
        present.add(str(doc.get("document_id") or ""))
        filled += 1
    return final, filled
