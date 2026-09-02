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
    ents = ext.extract(
        "Do both Beauty And The Bad Man and Wild Child (Film) films share directors?"
    )
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


def main() -> None:
    tests = [
        test_extractor_english,
        test_extractor_and_split,
        test_extractor_connectives,
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
