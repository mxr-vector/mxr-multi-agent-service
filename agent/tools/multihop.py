"""Deterministic multihop anchor extraction, hop query building and merging.

Pure functions only (no IO, no LLM): the multihop evidence path must not add
online reflection calls, so every planning step here is rule-based and
auditable.  Each hop query carries provenance (source hop / anchor / optional
member document pointer) so evaluation can attribute failures per stage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 英文锚点最小长度与候选上限（限制每跳锚点数量，避免宽泛下钻）
_MIN_EN_PHRASE = 2
MAX_QUESTION_ANCHORS = 3
MAX_CONTEXT_ANCHORS = 4
MAX_HOP_QUERIES = 3

# 常见句首/疑问/关系功能词：不构成实体锚点
_EN_STOP = {
    "the",
    "a",
    "an",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "and",
    "or",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "who",
    "whom",
    "whose",
    "what",
    "which",
    "when",
    "where",
    "why",
    "how",
    "did",
    "do",
    "does",
    "has",
    "have",
    "had",
    "both",
    "from",
    "with",
    "by",
    "as",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "there",
    "their",
    "his",
    "her",
    "not",
    "no",
    "yes",
    "if",
    "than",
    "then",
    "also",
    "into",
    "about",
    "after",
    "before",
    "same",
    "other",
    "more",
    "most",
    "some",
    "any",
    "all",
    "each",
    "every",
    "one",
    "two",
    "three",
    "film",
    "films",
}

# 低置信度锚点阈值：低于该分不触发下钻
MIN_ANCHOR_CONFIDENCE = 2

_EN_PHRASE_RE = re.compile(r"[A-Z][A-Za-z0-9'’.-]*(?:\s+[A-Za-z0-9'’.-]+)*")
_CJK_RUN_RE = re.compile(r"[\u3400-\u9fff]{2,}")
# 实体短语内部允许的小写连接词（区分 "Edward Watson was ..." 与
# "Waldrada of Lotharingia"：was/the-of 类动词不在列表内即断开）
_EN_CONNECTIVES = {
    "of",
    "the",
    "and",
    "for",
    "at",
    "by",
    "van",
    "von",
    "de",
    "la",
    "le",
    "du",
    "da",
    "del",
    "di",
    "bin",
    "ibn",
    "al",
    "der",
    "den",
}
_PUNCT_SPLIT_RE = re.compile(r"[,;:!?\u3002\uff0c\uff1b]+")


@dataclass(frozen=True)
class Anchor:
    """One auditable anchor used to build a hop query."""

    text: str
    kind: str  # entity
    source: str  # question | hop:<n> | wiki
    confidence: int = 1
    source_document: str | None = None


@dataclass(frozen=True)
class HopQuery:
    """Independent hop query with full provenance metadata."""

    query: str
    source_hop: int
    anchors: tuple[str, ...]
    source_documents: tuple[str, ...] = ()
    member_hint: str | None = None
    # 保留原问题语义主干（锚点仅作补充），避免截断实体片段弱于原问题
    base_question: str | None = None


@dataclass
class HopResult:
    """Retrieval output of one hop (docs scored by that hop's own rerank)."""

    hop: int
    query: str
    docs: list = field(default_factory=list)
    ok: bool = True
    error: str | None = None


def extract_english_phrases(text: str, limit: int = 12) -> list[str]:
    """Deterministic capitalized-phrase extraction (no POS model needed).

    A phrase run breaks at any lowercase-initial word, so sentence fragments
    like "Edward Watson was the son of" collapse to "Edward Watson".
    """
    phrases: dict[str, int] = {}
    # 先按标点断开，避免 "Edward Watson, Viscount ..." 被逗号拖尾丢弃
    for segment in _PUNCT_SPLIT_RE.split(text or ""):
        for match in _EN_PHRASE_RE.finditer(segment):
            tokens = match.group(0).split()
            # 大写词起头、仅允许连接词小写续接：贪心切出所有实体链
            index = 0
            while index < len(tokens):
                if not tokens[index][:1].isupper():
                    index += 1
                    continue
                end = index + 1
                while end < len(tokens):
                    token = tokens[end]
                    if token[:1].isupper() or token.casefold() in _EN_CONNECTIVES:
                        end += 1
                        continue
                    break
                run = tokens[index:end]
                index = end
                # 去掉尾部连接词/功能词（"Film)"、"Of" 等片段）与句首代词
                while (
                    run
                    and run[-1].casefold().strip("().") in _EN_STOP | _EN_CONNECTIVES
                ):
                    run.pop()
                while run and len(run) > 1 and run[0].casefold() in _EN_STOP:
                    run.pop(0)
                if not run:
                    continue
                phrase = " ".join(run).strip("().,;:")
                if len(phrase) < _MIN_EN_PHRASE:
                    continue
                key = phrase.casefold()
                phrases[key] = phrases.get(key, 0) + 1
    ranked = sorted(phrases.items(), key=lambda item: (-item[1], item[0]))
    return [phrase for phrase, _ in ranked[:limit]]


def extract_chinese_terms(text: str, limit: int = 8) -> list[str]:
    """Continuous CJK runs as coarse anchors."""
    runs: dict[str, int] = {}
    for match in _CJK_RUN_RE.finditer(text or ""):
        run = match.group(0)
        runs[run] = runs.get(run, 0) + 1
    ranked = sorted(runs.items(), key=lambda item: (-item[1], item[0]))
    return [run for run, _ in ranked[:limit]]


def extract_anchors(
    question: str,
    context_texts: tuple[str, ...] = (),
    wiki_entities: tuple[str, ...] = (),
) -> list[Anchor]:
    """Extract auditable entity anchors from the question, hop context and wiki pages.

    Question entities are always kept (highest confidence); context/wiki
    anchors are frequency-ranked and capped.
    """
    anchors: list[Anchor] = []
    seen: set[str] = set()

    def add(text: str, kind: str, source: str, confidence: int) -> None:
        key = text.casefold()
        if not text or key in seen:
            return
        seen.add(key)
        anchors.append(
            Anchor(text=text, kind=kind, source=source, confidence=confidence)
        )

    for phrase in extract_english_phrases(question, MAX_QUESTION_ANCHORS):
        add(phrase, "entity", "question", 3)
    for run in extract_chinese_terms(question, MAX_QUESTION_ANCHORS):
        if len(run) >= 2:
            add(run, "entity", "question", 3)
    for entity in wiki_entities[:MAX_QUESTION_ANCHORS]:
        add(str(entity).strip(), "entity", "wiki", 2)
    for ctx in context_texts[:6]:
        for phrase in extract_english_phrases(ctx, MAX_CONTEXT_ANCHORS):
            add(phrase, "entity", "context", 1)
        for run in extract_chinese_terms(ctx, MAX_CONTEXT_ANCHORS):
            add(run, "entity", "context", 1)

    return anchors


def build_hop_queries(
    question: str,
    first_hop_docs: list[dict],
    navigation: list[dict] | None = None,
    max_queries: int = MAX_HOP_QUERIES,
) -> list[HopQuery]:
    """Compose independent hop-2+ queries from anchors with provenance.

    Strategy: entity anchors from first-hop candidates that differ from the
    question entities form focus queries (question text stays the semantic
    stem).  Effective wiki member pointers may add one member-hint query.
    Generic wiki pages contribute nothing here.
    """
    navigation = navigation or []
    question_entities = extract_english_phrases(question, MAX_QUESTION_ANCHORS)
    question_entities += [
        run
        for run in extract_chinese_terms(question, MAX_QUESTION_ANCHORS)
        if run not in question_entities
    ]
    queries: list[HopQuery] = []
    used: set[str] = set()

    def push(
        focus: str,
        anchors: tuple[str, ...],
        docs: tuple[str, ...],
        member: str | None = None,
    ) -> None:
        # 原问题作语义主干 + 锚点聚焦补充：截断的实体片段单独成句时
        # 语义信号弱于原问题（评测已验证），拼接后交给独立 rerank 排序
        query = f"{question} Focus: {focus}".strip()
        key = query.casefold()
        if not focus.strip() or key in used or len(queries) >= max_queries:
            return
        used.add(key)
        queries.append(
            HopQuery(
                query=query,
                source_hop=1,
                anchors=anchors,
                source_documents=docs,
                member_hint=member,
                base_question=question,
            )
        )

    # 1) 第一跳候选中的新实体（区别于问题实体）
    q_keys = {e.casefold() for e in question_entities}
    context_entities: list[tuple[str, str]] = []
    for doc in first_hop_docs[:5]:
        doc_id = str(doc.get("document_id") or "")
        for phrase in extract_english_phrases(
            str(doc.get("text", "")), MAX_CONTEXT_ANCHORS
        ):
            if phrase.casefold() not in q_keys:
                context_entities.append((phrase, doc_id))
        for run in extract_chinese_terms(str(doc.get("text", "")), MAX_CONTEXT_ANCHORS):
            if run not in q_keys:
                context_entities.append((run, doc_id))
    for phrase, doc_id in context_entities[:4]:
        push(phrase, (phrase,), (doc_id,) if doc_id else ())

    # 2) 有效 wiki 页成员指针：仅当页面实体与问题实体重合（门控由调用方保证）
    for page in navigation:
        page_entities = {str(e).casefold() for e in page.get("entities") or []}
        overlap = any(e.casefold() in page_entities for e in question_entities)
        members = page.get("documents") or []
        if overlap and members and question_entities:
            entity = question_entities[0]
            push(
                entity,
                (entity,),
                (),
                member=str(members[0]),
            )
            break
    return queries


# ---------- 候选合并：多路汇池 + document 级去重（v2：终排由调用方对原问题统一重排） ----------
def _best_chunk_per_document(docs: list[dict]) -> list[dict]:
    """Same document_id appears once: keep its highest-scored chunk."""
    best: dict[str, dict] = {}
    order: list[str] = []
    for doc in docs:
        doc_id = str(doc.get("document_id") or doc.get("point_id") or id(doc))
        score = doc.get("score")
        score = score if isinstance(score, (int, float)) else float("-inf")
        current = best.get(doc_id)
        if current is None:
            best[doc_id] = {**doc, "score": score}
            order.append(doc_id)
            continue
        cur_score = current.get("score")
        cur_score = cur_score if isinstance(cur_score, (int, float)) else float("-inf")
        if score > cur_score:
            best[doc_id] = {**doc, "score": score}
    return [best[doc_id] for doc_id in order]


def collect_hop_pool(
    hop_results: list[HopResult],
    merge_pool_size: int,
) -> tuple[list[dict], dict]:
    """Merge per-hop reranked candidates into one pool (v2 merge strategy).

    各跳 rerank 分数是对不同 query 打分，跨跳不可比；因此本层只做文档级去重
    与 source_hops 溯源，不做跨跳比分裁剪。最终 top-k 由调用方对原问题
    统一重排决定，各跳的价值是"把单路召不回的文档送进决赛圈"。
    返回（合并池, {hop_coverage}）；合并池按 hop 序 + 跳内 rerank 序排列。
    """
    coverage: dict[str, dict] = {}
    for result in hop_results:
        coverage[f"hop{result.hop}"] = {
            "query": result.query,
            "candidates": len(result.docs),
            "ok": result.ok,
            "error": result.error,
            "in_final": False,
        }
    if merge_pool_size <= 0:
        return [], {"hop_coverage": coverage}

    pool: list[dict] = []
    seen: set[str] = set()

    def doc_key(doc: dict) -> str:
        return str(doc.get("document_id") or doc.get("point_id") or id(doc))

    for result in sorted(hop_results, key=lambda item: item.hop):
        if not result.ok or not result.docs:
            continue
        for doc in _best_chunk_per_document(result.docs):
            if len(pool) >= merge_pool_size:
                break
            key = doc_key(doc)
            if key in seen:
                for chosen in pool:
                    if doc_key(chosen) == key and result.hop not in chosen.get(
                        "source_hops", []
                    ):
                        chosen.setdefault("source_hops", []).append(result.hop)
                continue
            entry = dict(doc)
            entry.setdefault("source_hops", []).append(result.hop)
            pool.append(entry)
            seen.add(key)
    return pool, {"hop_coverage": coverage}


# ---------- Wiki 有效性门控（D4，通用性由统计判据提供，无硬编码词表） ----------
def _phrase_tokens(phrase: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in re.findall(r"[A-Za-z0-9'’-]+", phrase))


def _entity_match(question_phrases: tuple[str, ...], page_entities: list[str]) -> bool:
    """Overlap test robust to multi-word entities (no word splitting traps).

    A page entity matches when it casefold-contains a question phrase (or vice
    versa), or when the entity's significant tokens form a contiguous sequence
    inside a question phrase's tokens (handles 'Grown Ups (film)' vs 'Grown Ups').
    """
    for phrase in question_phrases:
        p_cf = phrase.casefold()
        p_tokens = _phrase_tokens(phrase)
        if not p_tokens:
            continue
        for entity in page_entities:
            e_cf = str(entity).casefold()
            if not e_cf:
                continue
            if p_cf in e_cf or e_cf in p_cf:
                return True
            e_tokens = tuple(
                token
                for token in _phrase_tokens(e_cf)
                if not re.match(r"^[0-9a-f]{16,}", token)
            )
            if len(e_tokens) >= 2:
                for start in range(0, len(p_tokens) - len(e_tokens) + 1):
                    if p_tokens[start : start + len(e_tokens)] == e_tokens:
                        return True
    return False


def gate_navigation(
    question: str,
    navigation: list[dict] | None,
    retrieved_docs: list[dict] | None = None,
    generic_terms: set[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Split wiki pages into effective vs generic for retrieval influence.

    A page is effective when its entities overlap the question phrases, or its
    member documents overlap already-retrieved evidence.  ``generic_terms``
    (statistical criterion from the entity index: corpus document frequency
    above threshold, no vocabularies) filters page entities/keywords before
    matching; without it, overlap-only judgment applies.  Generic pages stay
    visible to the model but MUST NOT influence dense/sparse/rerank inputs.
    Returns (effective, generic).
    """
    navigation = navigation or []
    if not navigation:
        return [], []
    question_phrases = tuple(
        extract_english_phrases(question, 8) + extract_chinese_terms(question, 8)
    )
    retrieved_ids = {
        str(doc.get("document_id") or "") for doc in (retrieved_docs or [])
    }

    def significant(values: list[str]) -> list[str]:
        if not generic_terms:
            return values
        return [value for value in values if str(value).casefold() not in generic_terms]

    effective: list[dict] = []
    generic: list[dict] = []
    for page in navigation:
        members = {str(m) for m in page.get("documents") or []}
        entity_overlap = _entity_match(
            question_phrases, significant(list(page.get("entities") or []))
        )
        if not entity_overlap:
            entity_overlap = _entity_match(
                question_phrases, significant(list(page.get("keywords") or []))
            )
        member_overlap = bool(retrieved_ids and retrieved_ids & members)
        if entity_overlap or member_overlap:
            page = dict(page)
            page["navigation_gate"] = {
                "entity_overlap": entity_overlap,
                "member_overlap": member_overlap,
            }
            effective.append(page)
        else:
            generic.append(page)
    return effective, generic
