"""Query-time entity linking and one-hop co-occurrence expansion (design D2).

Pure functions over plain data structures (inverted postings as mappings,
generic entities as sets).  No storage, no LLM, no hardcoded vocabularies:
genericness is decided by the caller-supplied ``generic`` set computed from
corpus document frequency (statistical criterion, design D5).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Mapping, Sequence

# 度数上限（防热门实体爆炸）：直达文档 cap A、扩展文档 cap B、桥接实体数
DEFAULT_CAP_A = 20
DEFAULT_CAP_B = 20
DEFAULT_BRIDGE_ENTITY_CAP = 8


@dataclass(frozen=True)
class ExpansionResult:
    """Outcome of entity linking + one-hop expansion for one question."""

    linked_entities: tuple[str, ...] = ()
    direct_docs: tuple[str, ...] = ()
    bridge_entities: tuple[str, ...] = ()
    expanded_docs: tuple[str, ...] = ()
    # 文档 → 使其入选的实体（直达文档为问题实体，扩展文档为桥接实体），
    # 供查询期取证定位"含该实体的叶块"（方向①：桥接段落未必是文档首块）
    doc_entity_provenance: tuple[tuple[str, str], ...] = ()
    degraded: bool = False  # 无可链接实体：不扩展（优雅降级）


def link_and_expand(
    question_entities: Sequence[str],
    postings: Mapping[str, Sequence[str]],
    doc_entities: Mapping[str, Sequence[str]],
    generic: set[str],
    *,
    cap_a: int = DEFAULT_CAP_A,
    cap_b: int = DEFAULT_CAP_B,
    bridge_entity_cap: int = DEFAULT_BRIDGE_ENTITY_CAP,
) -> ExpansionResult:
    """Deterministic two-hop traversal over the inverted index.

    hop 1: question entities → postings (skip generic) → direct docs (cap A)
    hop 2: direct docs' entities → co-occurrence ranking (skip generic and
           already-linked) → top bridge entities → postings → expanded docs
           (cap B, excluding direct docs).

    Degraded (no linkable entity) returns an empty result; callers treat it
    as "no expansion" and keep the existing retrieval path unchanged.
    """
    linked = []
    seen_linked: set[str] = set()
    for entity in question_entities:
        key = entity.casefold()
        if key in seen_linked or key in generic or key not in postings:
            continue
        seen_linked.add(key)
        linked.append(key)
    if not linked:
        return ExpansionResult(degraded=True)

    # hop 1：倒排直达（保序去重，限 cap A）
    direct_docs: list[str] = []
    seen_docs: set[str] = set()
    provenance: list[tuple[str, str]] = []
    for entity in linked:
        for doc_id in postings[entity]:
            if doc_id not in seen_docs:
                seen_docs.add(doc_id)
                direct_docs.append(doc_id)
                provenance.append((doc_id, entity))
                if len(direct_docs) >= cap_a:
                    break
        if len(direct_docs) >= cap_a:
            break

    # hop 2：直达文档的实体共现统计 → 桥接实体 → 扩展文档
    cooc: Counter = Counter()
    for doc_id in direct_docs:
        for entity in doc_entities.get(doc_id, ()):  # type: ignore[arg-type]
            key = entity.casefold()
            if key in generic or key in seen_linked:
                continue
            cooc[key] += 1
    bridge_entities = [
        entity for entity, _ in cooc.most_common(bridge_entity_cap)
    ]

    expanded_docs: list[str] = []
    seen_expanded: set[str] = set()
    for entity in bridge_entities:
        for doc_id in postings.get(entity, ()):
            if doc_id in seen_docs or doc_id in seen_expanded:
                continue
            seen_expanded.add(doc_id)
            expanded_docs.append(doc_id)
            provenance.append((doc_id, entity))
            if len(expanded_docs) >= cap_b:
                break
        if len(expanded_docs) >= cap_b:
            break

    return ExpansionResult(
        linked_entities=tuple(linked),
        direct_docs=tuple(direct_docs),
        bridge_entities=tuple(bridge_entities),
        expanded_docs=tuple(expanded_docs),
        doc_entity_provenance=tuple(provenance),
    )
