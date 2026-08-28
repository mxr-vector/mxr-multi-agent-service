"""LongBench v3 evidence gold, metrics, and reporting helpers.

The existing LongBench adapter has no retrieval qrels.  This module keeps the
answer paragraphs and the intermediate bridge paragraphs as separate records
so a navigation layer can be evaluated without pretending that a derived
paragraph is an annotated fact.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence

from common import compute_metrics, hit_positions, mean_std, normalize

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_CJK_RE = re.compile(r"[\u3400-\u9fff]{2,}")
_PUNCT_RE = re.compile(r"[。！？；，、,.!?;:\"'《》〈〉（）()\[\]【】\s]+")
_STOP_WORDS = {
    "about",
    "after",
    "also",
    "between",
    "could",
    "from",
    "have",
    "into",
    "more",
    "such",
    "than",
    "that",
    "their",
    "there",
    "these",
    "they",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "who",
    "why",
    "whose",
    "是",
    "什么",
    "哪些",
    "如何",
    "为什么",
    "以及",
    "关于",
}
_RELATION_WORDS = {
    "type",
    "types",
    "kind",
    "kinds",
    "class",
    "category",
    "part",
    "family",
    "group",
    "called",
    "known",
    "属于",
    "包括",
    "包含",
    "类型",
    "种类",
    "类别",
    "组成",
    "成员",
}


@dataclass(frozen=True)
class EvidenceParagraph:
    """One paragraph in the v3 gold set."""

    index: int
    source: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "source": self.source,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class V3Gold:
    """Paragraph-level evidence split into answer and bridge evidence."""

    answer: tuple[EvidenceParagraph, ...]
    bridge: tuple[EvidenceParagraph, ...]
    hops: tuple[tuple[int, ...], ...]
    hop_count: int
    question_type: str
    origin: str

    @property
    def answer_indices(self) -> list[int]:
        return [item.index for item in self.answer]

    @property
    def bridge_indices(self) -> list[int]:
        return [item.index for item in self.bridge]

    def to_dict(self) -> dict:
        return {
            "answer": [item.to_dict() for item in self.answer],
            "bridge": [item.to_dict() for item in self.bridge],
            "hops": [list(hop) for hop in self.hops],
            "hop_count": self.hop_count,
            "question_type": self.question_type,
            "origin": self.origin,
        }


def extract_question_entities(text: str) -> set[str]:
    """Extract stable bilingual entity-like phrases without an NLP dependency."""
    values = {token.casefold() for token in _TOKEN_RE.findall(text or "")}
    values.update(_CJK_RE.findall(text or ""))
    return {
        value
        for value in values
        if value not in _STOP_WORDS and len(value) >= 2
    }


def _paragraph_entities(text: str) -> set[str]:
    return extract_question_entities(text)


def _annotation_indices(row: dict, paragraphs: Sequence[str]) -> set[int]:
    """Read common paragraph-level support annotations when a dataset has them."""
    raw = (
        row.get("evidence_paragraphs")
        or row.get("supporting_paragraphs")
        or row.get("gold_paragraphs")
        or row.get("supporting_facts")
    )
    if not raw:
        return set()

    indices: set[int] = set()
    for item in raw if isinstance(raw, list) else [raw]:
        if isinstance(item, int):
            if 0 <= item < len(paragraphs):
                indices.add(item)
            continue
        if isinstance(item, str):
            value = normalize(item).casefold()
            indices.update(
                index
                for index, paragraph in enumerate(paragraphs)
                if value and value in normalize(paragraph).casefold()
            )
            continue
        if isinstance(item, (list, tuple)) and item:
            # HotpotQA-style [title, sentence_index] annotations.
            title = normalize(str(item[0])).casefold()
            sentence_index = item[1] if len(item) > 1 else None
            for index, paragraph in enumerate(paragraphs):
                normalized = normalize(paragraph).casefold()
                if title and title not in normalized:
                    continue
                if isinstance(sentence_index, int):
                    sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", paragraph)]
                    if sentence_index < len(sentences) and normalize(sentences[sentence_index]).casefold() in normalized:
                        indices.add(index)
                else:
                    indices.add(index)
        elif isinstance(item, dict):
            candidate = item.get("paragraph_index", item.get("index"))
            if isinstance(candidate, int) and 0 <= candidate < len(paragraphs):
                indices.add(candidate)
    return indices


def _bridge_annotation_indices(row: dict, paragraphs: Sequence[str]) -> set[int]:
    """Read bridge-specific annotations without conflating answer evidence."""
    raw = (
        row.get("bridge_paragraphs")
        or row.get("bridge_evidence")
        or row.get("supporting_bridge_paragraphs")
    )
    if not raw:
        return set()
    isolated = {
        "evidence_paragraphs": raw,
        "supporting_paragraphs": None,
        "gold_paragraphs": None,
        "supporting_facts": None,
    }
    return _annotation_indices(isolated, paragraphs)


def _answer_indices(row: dict, paragraphs: Sequence[str]) -> tuple[set[int], str]:
    annotated = _annotation_indices(row, paragraphs)
    if annotated:
        return annotated, "annotated"

    answers = row.get("answers") or row.get("answer") or []
    if isinstance(answers, str):
        answers = [answers]
    normalized = [normalize(paragraph).casefold() for paragraph in paragraphs]
    found: set[int] = set()
    for answer in answers:
        value = normalize(str(answer)).casefold()
        if not value:
            continue
        found.update(index for index, paragraph in enumerate(normalized) if value in paragraph)
        if not any(value in paragraph for paragraph in normalized):
            fragments = sorted(
                {
                    normalize(part).casefold()
                    for part in _PUNCT_RE.split(str(answer))
                    if len(normalize(part)) >= 4
                },
                key=lambda item: (-len(item), item),
            )[:3]
            for fragment in fragments:
                found.update(index for index, paragraph in enumerate(normalized) if fragment in paragraph)
    return found, "answer_derived" if found else "unresolved"


def derive_bridge_paragraphs(
    question: str,
    paragraphs: Sequence[str],
    answer_indices: Iterable[int],
    *,
    max_bridge: int = 10,
) -> list[EvidenceParagraph]:
    """Derive bridge evidence using explicit, auditable lexical rules.

    A paragraph is a candidate when it either co-occurs with at least two
    question entities, or shares an entity with answer evidence while using a
    relation/hypernym marker.  Adjacent support is accepted only with a shared
    question entity.  Answer paragraphs are excluded from the bridge set.
    """
    answer_set = set(answer_indices)
    question_entities = extract_question_entities(question)
    if not question_entities:
        return []
    paragraph_entities = [_paragraph_entities(paragraph) for paragraph in paragraphs]
    answer_entities = set().union(*(paragraph_entities[index] for index in answer_set if 0 <= index < len(paragraphs)))
    relation_tokens = extract_question_entities(" ".join(_RELATION_WORDS))
    scored: list[tuple[int, int, str]] = []
    for index, paragraph in enumerate(paragraphs):
        if index in answer_set:
            continue
        entities = paragraph_entities[index]
        shared = question_entities & entities
        if len(shared) >= 2:
            scored.append((3, index, f"entity_cooccurrence:{','.join(sorted(shared))}"))
            continue
        relation_hit = bool(
            relation_tokens
            & extract_question_entities(paragraph)
            & _RELATION_WORDS
        ) or any(marker.casefold() in paragraph.casefold() for marker in _RELATION_WORDS)
        if shared and relation_hit and (answer_entities & entities):
            scored.append((2, index, f"entity_hypernym:{','.join(sorted(shared))}"))
            continue
        if shared and any(abs(index - answer_index) == 1 for answer_index in answer_set):
            scored.append((1, index, f"adjacent_entity_support:{','.join(sorted(shared))}"))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        EvidenceParagraph(index=index, source="derived", reason=reason)
        for _, index, reason in scored[:max_bridge]
    ]


def _question_type(row: dict, *, answer_count: int, bridge_count: int) -> str:
    explicit = str(row.get("question_type") or "").strip().lower()
    if explicit in {"single-hop", "multi-hop", "cross-document", "topic-ambiguous"}:
        return explicit
    subset = str(row.get("subset") or "").lower()
    if row.get("topic_ambiguous"):
        return "topic-ambiguous"
    try:
        if row.get("document_count", 0) and int(row["document_count"]) > 1:
            return "cross-document"
    except (TypeError, ValueError):
        pass
    if subset in {"2wikimqa", "musique", "hotpotqa", "dureader"}:
        return "cross-document" if subset == "dureader" else "multi-hop"
    return "single-hop" if answer_count or not bridge_count else "topic-ambiguous"


def _hop_count(row: dict, *, bridge_count: int) -> int:
    value = row.get("hop_count") or row.get("hops")
    if isinstance(value, (list, tuple)):
        return max(1, len(value))
    try:
        if value is not None:
            return max(1, int(value))
    except (TypeError, ValueError):
        pass
    return 2 if bridge_count else 1


def build_v3_gold(row: dict, *, max_bridge: int = 10) -> V3Gold:
    """Build the paragraph-level v3 record for a LongBench-like row."""
    paragraphs = [part.strip() for part in str(row.get("context") or "").split("\n") if part.strip()]
    answer_indices, origin = _answer_indices(row, paragraphs)
    bridge = derive_bridge_paragraphs(
        str(row.get("question") or row.get("input") or ""),
        paragraphs,
        answer_indices,
        max_bridge=max_bridge,
    )
    annotated_bridge = _bridge_annotation_indices(row, paragraphs)
    if annotated_bridge:
        bridge = [
            EvidenceParagraph(index=index, source="annotated", reason="bridge_annotation")
            for index in sorted(annotated_bridge)
            if index not in answer_indices
        ]
    hop_count = _hop_count(row, bridge_count=len(bridge))
    question_type = _question_type(row, answer_count=len(answer_indices), bridge_count=len(bridge))
    answer = tuple(
        EvidenceParagraph(index=index, source=origin, reason="answer_match")
        for index in sorted(answer_indices)
    )
    # The default hop split is intentionally conservative: answer and bridge
    # evidence remain separate, while custom annotated hop groups are honored.
    raw_hops = row.get("evidence_hops") or row.get("hop_paragraphs")
    if isinstance(raw_hops, list) and raw_hops:
        hops = tuple(
            tuple(int(index) for index in hop if isinstance(index, int))
            for hop in raw_hops
            if isinstance(hop, (list, tuple))
        )
    elif bridge:
        hops = (tuple(item.index for item in bridge), tuple(item.index for item in answer))
    else:
        hops = (tuple(item.index for item in answer),)
    return V3Gold(
        answer=answer,
        bridge=tuple(bridge),
        hops=tuple(hop for hop in hops if hop),
        hop_count=max(hop_count, len(hops) or 1),
        question_type=question_type,
        origin=origin,
    )


def _map_indices(indices: Iterable[int], mapping: dict[str, str], qid: str) -> list[str]:
    values = []
    for index in indices:
        value = mapping.get(f"lb:{qid}:{index}")
        if value:
            values.append(str(value))
    return list(dict.fromkeys(values))


def attach_v3_gold(row: dict, mapping: dict[str, str]) -> dict:
    """Attach document-level v3 gold fields to a loaded query row."""
    gold = build_v3_gold(row)
    qid = str(row["qid"])
    row = dict(row)
    row["v3_gold"] = gold.to_dict()
    row["answer_gold_docs"] = _map_indices(gold.answer_indices, mapping, qid)
    row["bridge_gold_docs"] = _map_indices(gold.bridge_indices, mapping, qid)
    row["hop_gold_docs"] = [
        _map_indices(hop, mapping, qid) for hop in gold.hops
    ]
    row["gold_origin"] = gold.origin
    row["bridge_origin"] = (
        "annotated"
        if any(item.source == "annotated" for item in gold.bridge)
        else "derived"
        if gold.bridge
        else "none"
    )
    row["question_type"] = gold.question_type
    row["hop_count"] = gold.hop_count
    # Existing retrieval runners use gold_docs; preserve that contract for the
    # answer path while the v3 fields remain available to the evaluator.
    row["gold_docs"] = row["answer_gold_docs"]
    return row


def _recall_at(ranked: list[dict], gold: Iterable[str], k: int, mode: str) -> float | None:
    values = list(dict.fromkeys(str(value) for value in gold if value))
    if not values:
        return None
    positions = hit_positions(ranked, values, mode=mode)
    return sum(position <= k for position in positions) / len(values)


def _hop_success_at(ranked: list[dict], hops: Sequence[Sequence[str]], k: int, mode: str) -> float | None:
    groups = [list(dict.fromkeys(str(value) for value in hop if value)) for hop in hops]
    groups = [group for group in groups if group]
    if not groups:
        return None
    return sum(bool(hit_positions(ranked[:k], group, mode=mode)) for group in groups) / len(groups)


def compute_v3_metrics(
    ranked: list[dict],
    answer_gold: Iterable[str],
    bridge_gold: Iterable[str],
    hop_gold: Sequence[Sequence[str]],
    ks: Iterable[int],
    *,
    mode: str = "doc",
) -> dict | None:
    """Return v2 metrics plus bridge recall and hop success rate."""
    answer_metrics = compute_metrics(ranked, answer_gold, ks, mode=mode)
    if answer_metrics is None:
        return None
    result = dict(answer_metrics)
    result["bridge_recall"] = {
        int(k): _recall_at(ranked, bridge_gold, int(k), mode)
        for k in ks
    }
    result["hop_success_rate"] = {
        int(k): _hop_success_at(ranked, hop_gold, int(k), mode)
        for k in ks
    }
    return result


def summarize_v3(
    results: Sequence[dict],
    ks: Iterable[int] = (1, 3, 5, 10),
    *,
    strict_only: bool = False,
) -> dict:
    """Aggregate v3 metrics by question type and hop count.

    ``strict_only`` excludes rows whose bridge gold is derived.  Derived rows
    are still reported in the regular disclosure summary.
    """
    ks = tuple(int(k) for k in ks)
    filtered = [
        item
        for item in results
        if not strict_only
        or (
            item.get("gold_origin") == "annotated"
            and item.get("bridge_origin", "none") != "derived"
        )
    ]
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in filtered:
        groups[str(item.get("question_type") or "unknown")].append(item)
    hop_groups: dict[str, list[dict]] = defaultdict(list)
    for item in filtered:
        hop_groups[str(item.get("hop_count") or 1)].append(item)

    def aggregate(items: Sequence[dict]) -> dict:
        buckets: dict[str, list[float]] = defaultdict(list)
        counts = Counter()
        for item in items:
            if item.get("status") != "ok":
                counts["failed"] += 1
                continue
            metrics = compute_v3_metrics(
                item.get("candidates") or [],
                item.get("answer_gold_docs") or item.get("gold_docs") or [],
                item.get("bridge_gold_docs") or [],
                item.get("hop_gold_docs") or [],
                ks,
                mode="doc",
            )
            if metrics is None:
                counts["empty_answer_gold"] += 1
                continue
            counts["valid"] += 1
            buckets["mrr"].append(metrics["mrr"])
            for key in ("recall", "precision", "ndcg"):
                for k in ks:
                    value = metrics[k][key]
                    buckets[f"{key}@{k}"].append(value)
            # hit@k：top-k 中至少命中一个 gold 文档的题占比（体验口径：答对只需
            # 一个含答案的文档，不需要 gold 全中；与 QA contain-match 直接对应）
            gold_set = set(item.get("answer_gold_docs") or item.get("gold_docs") or [])
            for k in ks:
                topk_ids = {
                    str(c.get("document_id"))
                    for c in (item.get("candidates") or [])[:k]
                }
                buckets[f"hit@{k}"].append(1.0 if gold_set & topk_ids else 0.0)
            for k in ks:
                for metric_name in ("bridge_recall", "hop_success_rate"):
                    value = metrics[metric_name][k]
                    if value is not None:
                        buckets[f"{metric_name}@{k}"].append(value)
        return {
            "counts": dict(counts),
            "metrics": {
                key: mean_std(values) for key, values in sorted(buckets.items())
            },
        }

    return {
        "strict_only": strict_only,
        "total": len(filtered),
        "by_question_type": {key: aggregate(value) for key, value in sorted(groups.items())},
        "by_hop_count": {key: aggregate(value) for key, value in sorted(hop_groups.items(), key=lambda item: int(item[0]))},
        "overall": aggregate(filtered),
    }


def _fmt(value: tuple[float, float] | None) -> str:
    return "—" if value is None else f"{value[0]:.3f}±{value[1]:.3f}"


def render_v3_report(title: str, meta: dict, disclosure: dict, strict: dict | None = None) -> str:
    """Render a compact report with type and hop strata."""
    lines = [f"# {title}", ""]
    for key, value in meta.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "> Derived bridge gold is disclosed separately and is excluded from strict comparison.", ""])

    def section(label: str, summary: dict) -> None:
        lines.extend([f"## {label}", "", "| Metric | Value |", "|---|---|"])
        for key in ("mrr", "recall@10", "bridge_recall@10", "hop_success_rate@10"):
            lines.append(f"| {key} | {_fmt(summary.get('metrics', {}).get(key))} |")
        lines.append(f"| valid | {summary.get('counts', {}).get('valid', 0)} |")
        lines.append("")

    section("Overall disclosure", disclosure["overall"])
    lines.extend(["## By question type", "", "| Type | Recall@10 | Bridge Recall@10 | Hop Success Rate@10 |", "|---|---|---|---|"])
    for key, summary in disclosure["by_question_type"].items():
        metrics = summary["metrics"]
        lines.append(
            f"| {key} | {_fmt(metrics.get('recall@10'))} | {_fmt(metrics.get('bridge_recall@10'))} | {_fmt(metrics.get('hop_success_rate@10'))} |"
        )
    lines.extend(["", "## By hop count", "", "| Hops | Recall@10 | Bridge Recall@10 | Hop Success Rate@10 |", "|---|---|---|---|"])
    for key, summary in disclosure["by_hop_count"].items():
        metrics = summary["metrics"]
        lines.append(
            f"| {key} | {_fmt(metrics.get('recall@10'))} | {_fmt(metrics.get('bridge_recall@10'))} | {_fmt(metrics.get('hop_success_rate@10'))} |"
        )
    if strict is not None:
        lines.extend(["", "## Strict annotated comparison", ""])
        section("Strict annotated comparison", strict["overall"])
    return "\n".join(lines)
