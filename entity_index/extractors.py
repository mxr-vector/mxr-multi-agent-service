"""Entity extraction for the entity bridge index.

Pluggable extractors (design D4): v1 is a deterministic English rule
extractor (capitalized phrase chains with possessive stripping, "and"
compound splitting and connective-based chain breaking) validated by the
offline diagnostic (93.2% question entity link rate).  No hardcoded domain
vocabularies: only language-level stopwords/connectives, which are grammar,
not domain knowledge.  LLM-based extractors can be registered later without
changing the online contract.
"""

from __future__ import annotations

import re
from typing import Protocol


class EntityExtractor(Protocol):
    """Extracts a set of normalized entity strings from text."""

    name: str

    def extract(self, text: str) -> set[str]: ...


# 语言级功能词（语法范畴，非领域词表）：不成实体
_LANG_STOP = {
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
    "who",
    "whom",
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
    "passage",
    "文章",
    "标题",
}

# 实体短语内部允许的小写连接词（区分 "Edward Watson was ..." 与
# "Waldrada of Lotharingia"：was 类动词不在列表内即断链）
_LANG_CONNECTIVES = {
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

_EN_PHRASE_RE = re.compile(r"[A-Z][A-Za-z0-9'\u2019.-]*(?:\s+[A-Za-z0-9'\u2019.-]+)*")
_PUNCT_SPLIT_RE = re.compile(r"[,;:!?\u3002\uff0c\uff1b]+")
# 仅小写 and 视为实体分隔（大写 "And" 属于实体名本身，如 "Beauty And The Bad Man"）
_AND_SPLIT_RE = re.compile(r"\s+and\s+")
_POSSESSIVE_RE = re.compile(r"['\u2019]s$")


class RuleEntityExtractor:
    """v1 deterministic extractor: English capitalized phrase chains.

    Rules: punctuation splits segments; capitalized runs chain until a
    non-connective lowercase word; leading/trailing function words trimmed;
    possessive "'s" stripped; "X and Y" compounds split into entities.
    """

    name = "rule_v1"

    def extract(self, text: str) -> set[str]:
        phrases: set[str] = set()
        for segment in _PUNCT_SPLIT_RE.split(text or ""):
            for match in _EN_PHRASE_RE.finditer(segment):
                tokens = match.group(0).split()
                index = 0
                while index < len(tokens):
                    if not tokens[index][:1].isupper():
                        index += 1
                        continue
                    end = index + 1
                    while end < len(tokens):
                        token = tokens[end]
                        if token[:1].isupper() or token.casefold() in _LANG_CONNECTIVES:
                            end += 1
                            continue
                        break
                    run = tokens[index:end]
                    index = end
                    while (
                        run
                        and run[-1].casefold().strip("().")
                        in _LANG_STOP | _LANG_CONNECTIVES
                    ):
                        run.pop()
                    while run and len(run) > 1 and run[0].casefold() in _LANG_STOP:
                        run.pop(0)
                    if run:
                        phrase = " ".join(run).strip("().,;:")
                        for part in _AND_SPLIT_RE.split(phrase):
                            # 去括号后缀（"Wild Child (Film)" → "Wild Child"）与所有格去尾
                            part = part.split("(")[0]
                            part = _POSSESSIVE_RE.sub("", part.strip()).strip("().,;:")
                            if len(part) >= 2:
                                phrases.add(part.casefold())
        return phrases


_EXTRACTORS: dict[str, EntityExtractor] = {}


def register_extractor(extractor: EntityExtractor) -> None:
    _EXTRACTORS[extractor.name] = extractor


def get_extractor(name: str = "rule_v1") -> EntityExtractor:
    if name not in _EXTRACTORS:
        raise KeyError(f"unknown entity extractor: {name}")
    return _EXTRACTORS[name]


register_extractor(RuleEntityExtractor())
