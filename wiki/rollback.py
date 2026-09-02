"""Explicit rollback and safety checks for the optional wiki layer."""

from __future__ import annotations

from wiki.storage import TopicPageStore


def rollback_topic_index(scope_id: str) -> dict:
    """Delete one independent topic collection and report the fallback contract.

    The evidence collections are never touched.  Callers should also set
    ``WIKI_ENABLED=false`` (or omit the wiki tool) before restarting workers.
    """
    store = TopicPageStore(scope_id)
    existed = store.collection_exists()
    store.delete_collection()
    return {
        "scope_id": str(scope_id),
        "collection": store.collection,
        "collection_deleted": existed,
        "evidence_collections_touched": False,
        "fallback": "knowledge_base_search",
        "next_step": "set WIKI_ENABLED=false and restart workers",
    }


def verify_evidence_fallback() -> dict:
    """Read-only verification that the evidence tool remains registered."""
    from agent.tools.rag_tools import TOOL_IMPLS, TOOL_KNOWLEDGE_BASE_SEARCH

    return {
        "knowledge_base_search_registered": TOOL_KNOWLEDGE_BASE_SEARCH in TOOL_IMPLS,
        "wiki_is_optional": True,
    }
