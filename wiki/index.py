"""End-to-end topic index construction and incremental invalidation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from wiki.clustering import (
    ClusterConfig,
    ClusterResult,
    apply_cluster_reviews,
    cluster_documents,
    find_cross_partition_duplicates,
    review_anomalous_clusters,
    review_cross_partition_duplicates,
)
from wiki.generator import generate_topic_pages
from wiki.models import TopicPage, WikiDocument
from wiki.storage import TopicPageStore
from wiki.vectors import build_document_vectors


@dataclass(frozen=True)
class TopicIndexBuildResult:
    scope_id: str
    version: int
    pages: tuple[TopicPage, ...]
    clusters: ClusterResult
    reviews: tuple[dict, ...]


class TopicIndexBuilder:
    """Build full indexes and replace only affected partitions when requested."""

    def __init__(
        self,
        *,
        cluster_config: ClusterConfig | None = None,
        embedding_client: Any | None = None,
        store_factory=TopicPageStore,
    ) -> None:
        self.cluster_config = cluster_config or ClusterConfig()
        self.embedding_client = embedding_client
        self.store_factory = store_factory

    async def build(
        self,
        documents: Sequence[WikiDocument | Any],
        scope_id: str,
        *,
        version: int | None = None,
        recreate: bool = False,
        generator=None,
        reviewer=None,
        vectors: Sequence[Any] | None = None,
    ) -> TopicIndexBuildResult:
        normalized = [
            item if isinstance(item, WikiDocument) else WikiDocument.from_record(item)
            for item in documents
        ]
        version = version or int(datetime.now(timezone.utc).timestamp())
        # Pre-computed document vectors (e.g. aggregated evidence embeddings)
        # skip re-embedding; otherwise the factory embeds in input order.
        if vectors is None:
            vectors = build_document_vectors(
                normalized, embedding_client=self.embedding_client
            )
        clusters = cluster_documents(list(vectors), self.cluster_config)
        reviews = await review_anomalous_clusters(clusters.clusters, reviewer=reviewer)
        cross_zone_pairs = find_cross_partition_duplicates(clusters.clusters)
        cross_zone_reviews = await review_cross_partition_duplicates(
            cross_zone_pairs, reviewer=reviewer
        )
        reviews.extend(cross_zone_reviews)
        reviewed_clusters = apply_cluster_reviews(clusters.clusters, reviews)
        pages = await generate_topic_pages(
            reviewed_clusters, version=version, generator=generator
        )
        # 页落盘前挂块级指针：查询期 wiki 命中按 chunk id 直查原文，
        # 不挂则在线回退文档级锚定（attach 失败不阻断构建）
        try:
            from wiki.pointers import attach_chunk_pointers

            pages = await attach_chunk_pointers(pages, str(scope_id))
        except Exception as exc:  # pragma: no cover - 指针缺失仅降低确定性
            from utils.logger import logger

            logger.warning(
                f"[WIKI] 块指针挂接失败，页按无指针落盘（在线走回退锚定）: {exc}"
            )
        store = self.store_factory(scope_id, embedding_client=self.embedding_client)
        if recreate:
            store.delete_collection()
        store.upsert_pages(pages, embedding_client=self.embedding_client)
        return TopicIndexBuildResult(
            scope_id=str(scope_id),
            version=version,
            pages=tuple(pages),
            clusters=ClusterResult(tuple(reviewed_clusters), clusters.stats),
            reviews=tuple(
                {
                    "cluster_id": review.cluster_id,
                    "keep": review.keep,
                    "merge_with": review.merge_with,
                    "split": review.split,
                    "reason": review.reason,
                }
                for review in reviews
            ),
        )

    def mark_document_dirty(self, document_id: str, scope_id: str) -> list[str]:
        """Mark impacted pages dirty without blocking document ingestion."""
        store = self.store_factory(scope_id, embedding_client=self.embedding_client)
        return store.mark_dirty([document_id])

    async def rebuild_dirty_partitions(
        self,
        documents: Sequence[WikiDocument | Any],
        scope_id: str,
        *,
        version: int | None = None,
        generator=None,
        reviewer=None,
    ) -> TopicIndexBuildResult | None:
        """Rebuild documents belonging to dirty pages' coarse partitions only."""
        store = self.store_factory(scope_id, embedding_client=self.embedding_client)
        dirty_pages = store.list_pages(dirty_only=True)
        partitions = {
            page.coarse_partition for page in dirty_pages if page.coarse_partition
        }
        if not partitions:
            return None
        normalized = [
            item if isinstance(item, WikiDocument) else WikiDocument.from_record(item)
            for item in documents
        ]
        partition_pages = [
            page for page in store.list_pages() if page.coarse_partition in partitions
        ]
        impacted_ids = {
            document_id for page in partition_pages for document_id in page.documents
        }
        impacted = [
            document
            for document in normalized
            if document.document_id in impacted_ids
            or str((document.metadata or {}).get("coarse_partition")) in partitions
        ]
        if not impacted:
            return None
        old_ids = [page.topic_id for page in partition_pages]
        store.delete_topic_ids(old_ids)
        return await self.build(
            impacted,
            scope_id,
            version=version,
            recreate=False,
            generator=generator,
            reviewer=reviewer,
        )


async def build_topic_index(
    documents: Sequence[WikiDocument | Any],
    scope_id: str,
    **kwargs,
) -> TopicIndexBuildResult:
    return await TopicIndexBuilder().build(documents, scope_id, **kwargs)
