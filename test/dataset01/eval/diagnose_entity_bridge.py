"""Offline diagnostic: can an entity inverted index + co-occurrence bridge
recover the bridge gold that the current anchor-based recall misses?

No storage writes, no LLM, no services: pure Python over the LongBench rows.
Entities are capitalized-phrase chains (English) extracted with the same rules
as agent.tools.multihop; paragraph granularity matches the evaluation corpus
(one context line == one document).

Metrics over multi-hop queries with non-empty bridge gold:
  link_rate        问题实体能在 context 段落中链接到的 query 占比
  gold_direct      bridge gold 段落本身含问题实体的占比（倒排直达上限）
  gold_cooc        gold 段落与"含问题实体的段落"共享实体的占比（一跳共现桥）
  gold_combined    direct ∪ cooc（实体索引的理论覆盖上限）
对比当前 bridge_recall@10=0.119，判断索引路线的空间大小。
"""

from __future__ import annotations

import argparse
from collections import Counter

from common import ensure_cfg_async
from longbench_eval import SUBSETS, load_rows, split_paragraphs
from v3 import attach_v3_gold


def extract_entities(text: str) -> set[str]:
    """Capitalized-phrase chains, casefolded (multihop.py 同款切链规则)."""
    import re

    stop = {
        "the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or",
        "is", "are", "was", "were", "who", "whom", "what", "which", "when",
        "where", "why", "how", "did", "do", "does", "has", "have", "had",
        "both", "from", "with", "by", "as", "it", "its", "this", "that",
        "there", "their", "his", "her", "not", "passage", "文章", "标题",
    }
    connectives = {"of", "the", "and", "for", "at", "by", "van", "von", "de", "la", "le"}
    phrases: set[str] = set()
    for segment in re.split(r"[,;:!?\u3002\uff0c\uff1b]+", text or ""):
        for match in re.finditer(r"[A-Z][A-Za-z0-9'\u2019.-]*(?:\s+[A-Za-z0-9'\u2019.-]+)*", segment):
            tokens = match.group(0).split()
            index = 0
            while index < len(tokens):
                if not tokens[index][:1].isupper():
                    index += 1
                    continue
                end = index + 1
                while end < len(tokens):
                    token = tokens[end]
                    if token[:1].isupper() or token.casefold() in connectives:
                        end += 1
                        continue
                    break
                run = tokens[index:end]
                index = end
                while run and run[-1].casefold().strip("().") in stop | connectives:
                    run.pop()
                while run and len(run) > 1 and run[0].casefold() in stop:
                    run.pop(0)
                if run:
                    phrase = " ".join(run).strip("().,;:")
                    # 所有格去尾 + 小写 and 连接的复合实体拆分（大写 And 属实体名）
                    parts = re.split(r"\s+and\s+", phrase)
                    for part in parts:
                        part = part.split("(")[0]
                        part = re.sub(r"['\u2019]s$", "", part.strip()).strip("().,;:")
                        if len(part) >= 2:
                            phrases.add(part.casefold())
    return phrases


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subsets", default="2wikimqa,hotpotqa,musique")
    args = parser.parse_args()

    # gold 映射只用于取 bridge 段落索引，诊断不需要 doc-map
    rows = [
        attach_v3_gold(row, {})
        for row in load_rows([s.strip() for s in args.subsets.split(",") if s.strip()])
    ]

    stats = Counter()
    entity_doc_counts: Counter = Counter()
    sample_misses = []

    for row in rows:
        if row.get("question_type") != "multi-hop":
            continue
        gold = row.get("v3_gold") or {}
        bridge_idx = [item["index"] for item in (gold.get("bridge") or [])]
        if not bridge_idx:
            continue
        stats["queries"] += 1
        paragraphs = split_paragraphs(row["context"])
        para_entities = [extract_entities(p) for p in paragraphs]
        for entities in para_entities:
            entity_doc_counts.update(entities)

        q_entities = extract_entities(row["question"])
        linked = {e for e in q_entities if entity_doc_counts.get(e)}
        if linked:
            stats["link_ok"] += 1

        direct_hit = False
        cooc_hit = False
        # 含问题实体的段落实体集合（一跳共现的桥）
        bridge_entities: set[str] = set()
        for idx, entities in enumerate(para_entities):
            if q_entities & entities:
                bridge_entities |= entities
        for gi in bridge_idx:
            if gi >= len(paragraphs):
                continue
            g_entities = para_entities[gi]
            if q_entities & g_entities:
                direct_hit = True
            if g_entities & bridge_entities:
                cooc_hit = True
        if direct_hit:
            stats["gold_direct"] += 1
        if cooc_hit:
            stats["gold_cooc"] += 1
        if direct_hit or cooc_hit:
            stats["gold_combined"] += 1
        elif len(sample_misses) < 3:
            sample_misses.append((row["qid"], row["question"][:80], sorted(q_entities)[:4]))

    n = stats["queries"]
    print(f"多跳且有 bridge gold 的 query 数: {n}")
    print(f"实体词表规模(全语料去重): {len(entity_doc_counts)}")
    print()
    for key, label in (
        ("link_ok", "问题实体可链接"),
        ("gold_direct", "gold 直达(含问题实体)"),
        ("gold_cooc", "gold 一跳共现可达"),
        ("gold_combined", "gold 组合覆盖上限"),
    ):
        print(f"  {label}: {stats[key]}/{n} = {stats[key]/n:.1%}")
    print()
    print("对比当前 bridge_recall@10 = 0.119；若组合覆盖显著更高，实体索引路线有空间")
    if sample_misses:
        print("\n组合覆盖仍失败的样例:")
        for qid, q, ents in sample_misses:
            print(f"  {qid}: {q} | 实体={ents}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
