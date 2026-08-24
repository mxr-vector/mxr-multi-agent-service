"""Manual regression smoke test for Wiki navigation query isolation.

Run with::

    uv run python test/dataset01/eval/wiki_navigation_smoke.py

The test uses mocked retrieval/rerank boundaries, so it does not contact the
embedding, Qdrant, or rerank services.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

# Match the other dataset evaluation scripts when run by file path.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.tools.rag_tools import (
    _split_legacy_navigation_query,
    build_navigation_query,
    knowledge_base_search_impl,
)

KB_ID = "00000000-0000-0000-0000-000000000001"
QUESTION = "Which person founded the company?"
GENERIC_PAGE = {
    "title": "LongBench multi-hop question answering",
    "summary": "A navigation index for a dataset-level document cluster.",
    "keywords": ["LongBench", "multi-hop", "question answering"],
    "entities": [],
    "representative_questions": ["What is covered by this topic?"],
    "documents": ["doc-1"],
}


async def _assert_retrieval_isolated() -> None:
    observed: dict[str, object] = {}
    docs = [
        {
            "point_id": "point-1",
            "knowledge_base_id": KB_ID.replace("-", ""),
            "document_id": "doc-1",
            "text": "The evidence.",
        }
    ]

    def fake_retrieve(query, knowledge_base_ids):
        observed["retrieve_query"] = query
        return docs

    async def fake_rerank(query, candidates, top_n):
        observed["rerank_query"] = query
        return candidates[:top_n]

    async def fake_to_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    with patch("agent.tools.rag_tools.asyncio.to_thread", side_effect=fake_to_thread), patch(
        "agent.tools.rag_tools.hybrid_retrieve_multi", side_effect=fake_retrieve
    ), patch("agent.tools.rag_tools._rerank", side_effect=fake_rerank):
        outcome = await knowledge_base_search_impl(
            QUESTION,
            [KB_ID],
            top_k=1,
            navigation=[GENERIC_PAGE],
        )

    assert observed["retrieve_query"] == QUESTION
    assert observed["rerank_query"] == QUESTION
    assert outcome.metrics["navigation_guided"] is True
    assert outcome.metrics["reflect_rounds"] == 1

    legacy_query = f"{QUESTION}\nNavigation constraints:\ntopic=generic"
    assert _split_legacy_navigation_query(legacy_query) == (QUESTION, True)


def main() -> None:
    assert build_navigation_query(QUESTION, [GENERIC_PAGE]) == QUESTION
    asyncio.run(_assert_retrieval_isolated())
    print("wiki navigation safety smoke passed")


if __name__ == "__main__":
    main()
