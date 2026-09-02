"""Independent Qdrant storage for navigation topic pages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence
from uuid import NAMESPACE_URL, uuid5

from wiki.models import TopicPage

WIKI_COLLECTION_PREFIX = "wiki_topics"
WIKI_COLLECTION_VERSION = "v1"


def build_topic_collection_name(
    scope_id: str | None = None, version: str = WIKI_COLLECTION_VERSION
) -> str:
    """Build a collection name separate from every evidence collection."""
    scope = re.sub(r"[^a-zA-Z0-9_-]", "", str(scope_id or "global"))[:64] or "global"
    return f"{WIKI_COLLECTION_PREFIX}_{scope}_{version}"


@dataclass(frozen=True)
class WikiSearchHit:
    page: TopicPage
    score: float | None

    def to_dict(self) -> dict:
        value = self.page.to_dict()
        value["score"] = self.score
        if self.page.dirty:
            value["staleness_notice"] = (
                "topic page is dirty and may lag recent document changes"
            )
        return value


class TopicPageStore:
    """Qdrant adapter; page metadata is the durable version/dirty registry."""

    def __init__(
        self,
        scope_id: str | None = None,
        *,
        manager: Any | None = None,
        embedding_client: Any | None = None,
    ):
        self.scope_id = str(scope_id or "global")
        self.collection = build_topic_collection_name(self.scope_id)
        self._manager = manager
        self._embedding_client = embedding_client

    @property
    def manager(self):
        if self._manager is None:
            from database.qdrant_client import QdrantManager

            self._manager = QdrantManager(self.collection)
        return self._manager

    @property
    def embedding_client(self):
        if self._embedding_client is None:
            from model.embeddings.factory import EmbeddingFactory

            self._embedding_client = EmbeddingFactory.get_client()
        return self._embedding_client

    def _point_id(self, topic_id: str) -> str:
        """Map readable cluster ids to deterministic Qdrant-compatible UUIDs."""
        return str(uuid5(NAMESPACE_URL, f"{self.collection}:{topic_id}"))

    def collection_exists(self) -> bool:
        return bool(self.manager.client.collection_exists(self.collection))

    def is_empty(self) -> bool:
        if not self.collection_exists():
            return True
        records, _ = self.manager.client.scroll(
            collection_name=self.collection,
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        return not records

    def upsert_pages(
        self,
        pages: Sequence[TopicPage],
        *,
        recreate: bool = False,
        embedding_client: Any | None = None,
        batch_size: int = 64,
    ) -> list[str]:
        if not pages:
            return []
        client = embedding_client or self.embedding_client
        vectors = client.embed_documents([page.search_text for page in pages])
        if len(vectors) != len(pages):
            raise ValueError("topic page embedding count does not match page count")
        # Chunked upserts keep single requests far below Qdrant payload limits,
        # mirroring the evidence ingestion batching pattern.
        inserted: list[str] = []
        for start in range(0, len(pages), max(1, batch_size)):
            batch = pages[start : start + max(1, batch_size)]
            inserted.extend(
                self.manager.upsert_points(
                    vectors[start : start + max(1, batch_size)],
                    payloads=[page.to_payload() for page in batch],
                    ids=[self._point_id(page.topic_id) for page in batch],
                    ensure=True,
                )
            )
        return inserted

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        query_vector: Sequence[float] | None = None,
    ) -> list[WikiSearchHit]:
        if top_k <= 0 or self.is_empty():
            return []
        try:
            if query_vector is None:
                points = self.manager.search(query, top_k=top_k, with_payload=True)
            else:
                response = self.manager.client.query_points(
                    collection_name=self.collection,
                    query=list(query_vector),
                    limit=top_k,
                    with_payload=True,
                )
                points = response.points
        except Exception:
            return []
        return [
            WikiSearchHit(
                page=TopicPage.from_payload(
                    point.payload or {}, topic_id=str(point.id)
                ),
                score=getattr(point, "score", None),
            )
            for point in points
        ]

    def list_pages(self, *, dirty_only: bool = False) -> list[TopicPage]:
        if self.is_empty():
            return []
        records = []
        offset = None
        while True:
            batch, offset = self.manager.client.scroll(
                collection_name=self.collection,
                limit=1000,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            records.extend(batch)
            if offset is None or not batch:
                break
        pages = [
            TopicPage.from_payload(record.payload or {}, topic_id=str(record.id))
            for record in records
        ]
        return [page for page in pages if page.dirty] if dirty_only else pages

    def find_by_document_ids(self, document_ids: Iterable[str]) -> list[TopicPage]:
        wanted = {str(value) for value in document_ids}
        return [
            page for page in self.list_pages() if wanted.intersection(page.documents)
        ]

    def mark_dirty(
        self, document_ids: Iterable[str], *, reason: str = "document_changed"
    ) -> list[str]:
        pages = self.find_by_document_ids(document_ids)
        if not pages:
            return []
        topic_ids = [page.topic_id for page in pages]
        self.manager.client.set_payload(
            collection_name=self.collection,
            payload={"dirty": True, "dirty_reason": reason},
            points=[self._point_id(topic_id) for topic_id in topic_ids],
        )
        return topic_ids

    def delete_topic_ids(self, topic_ids: Iterable[str]) -> None:
        self.manager.delete_points([self._point_id(topic_id) for topic_id in topic_ids])

    def delete_collection(self) -> None:
        self.manager.delete_collection()

    def search_many(
        self, query: str, scopes: Sequence[str], top_k: int = 5
    ) -> list[WikiSearchHit]:
        stores = [
            TopicPageStore(scope, embedding_client=self._embedding_client)
            for scope in dict.fromkeys(str(value) for value in scopes if value)
        ]
        stores = [store for store in stores if not store.is_empty()]
        if not stores:
            return []
        query_vector = self.embedding_client.embed_query(query)
        hits: list[WikiSearchHit] = []
        for store in stores:
            hits.extend(store.search(query, top_k, query_vector=query_vector))
        hits.sort(
            key=lambda item: item.score if item.score is not None else 0.0, reverse=True
        )
        return hits[:top_k]


def search_topic_pages(
    query: str, scopes: Sequence[str], top_k: int = 5
) -> list[WikiSearchHit]:
    """Convenience entry point for the agent tool and evaluation scripts."""
    if not scopes:
        return []
    return TopicPageStore(scopes[0]).search_many(query, scopes, top_k)
