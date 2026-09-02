"""Smoke tests for multihop pure functions and LongBench title parsing.

Repo convention: no test framework — run directly:
  uv run python test/dataset01/eval/test_multihop_units.py
"""

from __future__ import annotations

import sys

import common  # noqa: F401  # 注入项目根到 sys.path


def test_anchor_extraction():
    from agent.tools.multihop import (
        MIN_ANCHOR_CONFIDENCE,
        extract_anchors,
        extract_english_phrases,
    )

    q = "Who is Edward Watson, Viscount Sondes's paternal grandfather?"
    phrases = extract_english_phrases(q)
    assert any("edward watson" in p.casefold() for p in phrases), phrases

    anchors = extract_anchors(q)
    entities = [
        a.text for a in anchors if a.kind == "entity" and a.source == "question"
    ]
    assert entities and all(
        a.confidence >= MIN_ANCHOR_CONFIDENCE for a in anchors if a.source == "question"
    )
    assert all(a.kind == "entity" for a in anchors)

    # 功能词不成锚点
    assert "the" not in [
        p.casefold() for p in extract_english_phrases("The film was directed by")
    ]


def test_hop_queries():
    from agent.tools.multihop import build_hop_queries

    q = "Who is Edward Watson, Viscount Sondes's paternal grandfather?"
    first_hop = [
        {"document_id": "d1", "text": "Edward Watson was the son of John Watson."}
    ]
    queries = build_hop_queries(q, first_hop)
    assert queries, "should build at least one hop query"
    primary = queries[0]
    assert primary.source_hop == 1
    assert primary.anchors
    # 第二跳查询不应是原问题整句（原问题作主干 + 新实体聚焦）
    assert primary.query != q
    # 新实体聚焦：John Watson 来自第一跳候选且不在问题实体中
    assert any("john watson" in a.casefold() for a in primary.anchors)
    # 每跳查询数量受限
    assert len(queries) <= 3

    # 无第一跳候选时不构造跳查询（优雅降级回单轮）
    q2 = "What year was the Eiffel Tower completed?"
    queries2 = build_hop_queries(q2, [])
    assert queries2 == []


def test_merge_coverage_and_dedup():
    from agent.tools.multihop import HopResult, collect_hop_pool

    hop0 = HopResult(
        hop=0,
        query="q0",
        docs=[
            {"document_id": "A", "point_id": "p1", "text": "a1", "score": 0.9},
            {"document_id": "A", "point_id": "p2", "text": "a2", "score": 0.5},
            {"document_id": "B", "point_id": "p3", "text": "b", "score": 0.8},
        ],
    )
    hop1 = HopResult(
        hop=1,
        query="q1",
        docs=[
            {"document_id": "C", "point_id": "p4", "text": "c", "score": 0.3},
            {"document_id": "A", "point_id": "p5", "text": "a3", "score": 0.95},
        ],
    )
    failed = HopResult(hop=2, query="q2", docs=[], ok=False, error="boom")

    pool, meta = collect_hop_pool([hop0, hop1, failed], merge_pool_size=10)
    doc_ids = [d["document_id"] for d in pool]
    # 同 document 只出现一次（A 保留跳内最高分块）
    assert len(doc_ids) == len(set(doc_ids)) == 3
    assert doc_ids.count("A") == 1
    # 双跳命中的文档带双 source_hops 溯源
    a_entry = next(d for d in pool if d["document_id"] == "A")
    assert set(a_entry["source_hops"]) == {0, 1}
    # 失败跳在覆盖指标中披露且不阻塞其他跳
    assert meta["hop_coverage"]["hop2"]["ok"] is False
    assert meta["hop_coverage"]["hop0"]["candidates"] == 3
    # 池容量限制生效
    capped, _ = collect_hop_pool([hop0, hop1], merge_pool_size=2)
    assert len(capped) == 2


def test_navigation_gating():
    from agent.tools.multihop import gate_navigation

    q = "Who directed Grown Ups?"
    generic_page = {
        "title": "2WikiMultiHopQA Document Cluster",
        "entities": ["LongBench", "2WikiMultiHopQA", "Wikipedia"],
        "keywords": ["multi-hop", "question answering"],
        "documents": ["x1"],
    }
    effective_page = {
        "title": "Grown Ups (film)",
        "entities": ["Grown Ups", "Dennis Dugan"],
        "keywords": ["comedy film"],
        "documents": ["m1"],
    }
    effective, generic = gate_navigation(q, [generic_page, effective_page])
    assert len(effective) == 1 and effective[0]["title"] == "Grown Ups (film)"
    assert effective[0]["navigation_gate"]["entity_overlap"] is True
    assert len(generic) == 1

    # 成员文档重合也算有效
    member_page = {
        "title": "Cluster p3",
        "entities": ["LongBench"],
        "keywords": [],
        "documents": ["m1"],
    }
    effective2, _ = gate_navigation(
        "unrelated question text", [member_page], retrieved_docs=[{"document_id": "m1"}]
    )
    assert (
        len(effective2) == 1
        and effective2[0]["navigation_gate"]["member_overlap"] is True
    )

    # 空导航
    assert gate_navigation(q, None) == ([], [])


def test_passage_title_parser():
    from longbench_eval import parse_passage_titles, split_paragraphs

    ctx = "Passage 1:\nWaldrada of Lotharingia\nWaldrada was the mistress.\nPassage 2:\nBiography Page\nMore text."
    records = parse_passage_titles(ctx)
    lines = split_paragraphs(ctx)
    assert len(records) == len(lines)
    by_idx = {r["line_idx"]: r for r in records}
    assert by_idx[0]["is_marker"]
    assert (
        by_idx[1]["passage_title"] == "Waldrada of Lotharingia"
        and by_idx[1]["is_title_line"]
    )
    assert (
        by_idx[2]["passage_title"] == "Waldrada of Lotharingia"
        and by_idx[2]["title_source"] == "parsed"
    )
    assert by_idx[4]["passage_title"] == "Biography Page"

    # dureader 格式
    ctx2 = "文章1\n标题：某贴吧帖子\n正文内容"
    recs2 = parse_passage_titles(ctx2)
    assert recs2[1]["passage_title"] == "某贴吧帖子"
    assert recs2[2]["passage_title"] == "某贴吧帖子"

    # 无标记回落 uri
    recs3 = parse_passage_titles("第一段\n第二段")
    assert all(r["title_source"] == "uri" for r in recs3)


def main() -> None:
    tests = [
        test_anchor_extraction,
        test_hop_queries,
        test_merge_coverage_and_dedup,
        test_navigation_gating,
        test_passage_title_parser,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
