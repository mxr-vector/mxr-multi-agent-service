"""Smoke tests for entity_index pure functions (tasks 1.1-1.4).

Repo convention: no test framework — run directly:
  uv run python test/dataset01/eval/test_entity_index_units.py
"""

from __future__ import annotations

import sys

import common  # noqa: F401  # 注入项目根到 sys.path


def test_extractor_english():
    from entity_index.extractors import RuleEntityExtractor

    ext = RuleEntityExtractor()
    ents = ext.extract("Who is Edward Watson, Viscount Sondes's paternal grandfather?")
    assert "edward watson" in ents, ents
    # 所有格去尾
    assert "viscount sondes" in ents, ents
    assert not any(e.endswith("'s") for e in ents)


def test_extractor_and_split():
    from entity_index.extractors import RuleEntityExtractor

    ext = RuleEntityExtractor()
    ents = ext.extract("Do both Beauty And The Bad Man and Wild Child (Film) films share directors?")
    assert "beauty and the bad man" in ents, ents
    assert "wild child" in ents, ents


def test_extractor_connectives():
    from entity_index.extractors import RuleEntityExtractor

    ext = RuleEntityExtractor()
    # 连接词保持实体链完整
    ents = ext.extract("Waldrada of Lotharingia was the mistress.")
    assert "waldrada of lotharingia" in ents, ents
    # 动词断链：不把整句当一个实体
    ents2 = ext.extract("Edward Watson was the son of John Watson.")
    assert "edward watson was the son" not in ents2, ents2
    assert "john watson" in ents2, ents2
    # 句首功能词不成实体
    ents3 = ext.extract("The film was directed by Nolan.")
    assert "the film" not in ents3 and "film" not in ents3, ents3
    assert "nolan" in ents3, ents3


def test_traverse_full_path():
    from entity_index.traverse import link_and_expand

    postings = {
        "alice": ["d1", "d2"],
        "john watson": ["d2", "d3"],
        "bob": ["d3", "d4"],
        "wonderland": ["d5"],
    }
    doc_entities = {
        "d1": ["alice", "john watson"],
        "d2": ["alice", "john watson", "wonderland"],
        "d3": ["john watson", "bob"],
    }
    result = link_and_expand(["alice"], postings, doc_entities, generic=set())
    assert not result.degraded
    assert result.linked_entities == ("alice",)
    assert result.direct_docs == ("d1", "d2")
    # 共现桥：john watson（2 次）优先于 wonderland（1 次）
    assert result.bridge_entities[0] == "john watson"
    # 扩展排除直达文档
    assert "d1" not in result.expanded_docs and "d2" not in result.expanded_docs
    assert "d3" in result.expanded_docs
    # 文档→实体归因：直达文档带问题实体，扩展文档带桥接实体
    prov = dict(result.doc_entity_provenance)
    assert prov["d1"] == "alice" and prov["d2"] == "alice"
    assert prov["d3"] == "john watson"
    # 归因与文档列表一一对应（无遗漏、无多余）
    assert set(prov) == set(result.direct_docs) | set(result.expanded_docs)


def test_traverse_generic_filter():
    from entity_index.traverse import link_and_expand

    postings = {"film": ["d1", "d2"], "alice": ["d3"]}
    doc_entities = {"d3": ["film", "alice"]}
    # film 为通用实体：只剩 alice 可链接；共现阶段 film 被过滤
    result = link_and_expand(["film", "alice"], postings, doc_entities, generic={"film"})
    assert result.linked_entities == ("alice",)
    assert result.bridge_entities == ()


def test_traverse_degrade():
    from entity_index.traverse import link_and_expand

    result = link_and_expand(["unknown entity"], {"alice": ["d1"]}, {}, generic=set())
    assert result.degraded
    assert result.direct_docs == () and result.expanded_docs == ()
    # 全部实体均为通用 → 同样降级
    result2 = link_and_expand(["film"], {"film": ["d1"]}, {}, generic={"film"})
    assert result2.degraded


def test_traverse_caps():
    from entity_index.traverse import link_and_expand

    postings = {f"e{i}": [f"d{i}"] for i in range(50)}
    postings["hub"] = [f"d{i}" for i in range(50)]
    doc_entities = {f"d{i}": ["hub", f"e{i}"] for i in range(50)}
    result = link_and_expand(
        [f"e{i}" for i in range(50)], postings, doc_entities,
        generic=set(), cap_a=5, cap_b=7, bridge_entity_cap=3,
    )
    assert len(result.direct_docs) == 5
    assert len(result.expanded_docs) <= 7
    assert len(result.bridge_entities) <= 3


def test_expansion_merge():
    from agent.tools.multihop import HopResult, collect_hop_pool
    from entity_index.merge import EXPANSION_HOP_LABEL, expansion_hop_result

    chunks = [
        {"document_id": "x1", "text": "chunk x1"},
        {"document_id": "x1", "text": "dup same doc"},
        {"document_id": "x2", "text": "chunk x2"},
        {"document_id": "x3", "text": "no-skip"},
    ]
    hop_result = expansion_hop_result(chunks, cap_c=2)
    assert hop_result is not None
    # 同文档去重 + cap_c 限量
    assert len(hop_result.docs) == 2
    assert {d["document_id"] for d in hop_result.docs} == {"x1", "x2"}
    assert hop_result.hop == EXPANSION_HOP_LABEL

    # 空块 → None（通道整体跳过）
    assert expansion_hop_result([]) is None
    assert expansion_hop_result([{"document_id": "x9"}]) is None  # 无 text

    # 与 collect_hop_pool 集成：扩展通道进合并池且溯源正确
    hop0 = HopResult(hop=0, query="q", docs=[{"document_id": "d0", "text": "t0", "score": 0.9}])
    pool, meta = collect_hop_pool([hop0, hop_result], merge_pool_size=10)
    ids = [d["document_id"] for d in pool]
    assert "d0" in ids and "x1" in ids
    assert meta["hop_coverage"][f"hop{EXPANSION_HOP_LABEL}"]["candidates"] == 2


def test_select_entity_chunk():
    from entity_index.store import select_entity_chunk

    chunks = [
        {"text": "Intro of the document"},
        {"text": "John Watson met Alice here."},
        {"text": "Later remarks"},
    ]
    # 实体命中：取含实体的块（大小写不敏感），而非首块
    picked = select_entity_chunk(chunks, "john watson")
    assert picked is chunks[1], picked
    # 实体未命中：回退首块
    assert select_entity_chunk(chunks, "nobody") is chunks[0]
    # 无实体（None）：回退首块；空列表 → None
    assert select_entity_chunk(chunks, None) is chunks[0]
    assert select_entity_chunk([], "alice") is None


def test_merge_final_with_expansion():
    from entity_index.merge import EXPANSION_HOP_LABEL, merge_final_with_expansion

    main_docs = [{"document_id": f"m{i}", "text": f"t{i}"} for i in range(10)]
    expansion_docs = [
        {"document_id": "m3", "text": "dup"},
        {"document_id": "e1", "text": "bridge one"},
        {"document_id": "e2", "text": "bridge two"},
        {"document_id": "e3", "text": "bridge three"},
    ]
    final, filled = merge_final_with_expansion(main_docs, expansion_docs, quota=2)
    # 席位限量、已存在文档跳过、注入尾部、带 hop 溯源
    assert filled == 2
    assert [d["document_id"] for d in final[-2:]] == ["e1", "e2"]
    assert final[-1]["source_hops"] == [EXPANSION_HOP_LABEL]
    assert len(final) == 12
    # quota=0 → 原样返回；扩展为空 → 0 席
    assert merge_final_with_expansion(main_docs, expansion_docs, quota=0)[1] == 0
    assert merge_final_with_expansion(main_docs, [], quota=2)[1] == 0


def main() -> None:
    tests = [
        test_extractor_english,
        test_extractor_and_split,
        test_extractor_connectives,
        test_traverse_full_path,
        test_traverse_generic_filter,
        test_traverse_degrade,
        test_traverse_caps,
        test_select_entity_chunk,
        test_expansion_merge,
        test_merge_final_with_expansion,
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
