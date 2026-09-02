"""Two-stage adaptive topic clustering and quality handling."""

from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Sequence

import numpy as np

from wiki.vectors import DocumentVector


@dataclass(frozen=True)
class ClusterConfig:
    coarse_target_size: int = 500
    min_cluster_size: int = 20
    max_cluster_size: int = 100
    variance_multiplier: float = 2.5
    noise_policy: str = "fallback_topic"
    random_state: int = 42

    def __post_init__(self) -> None:
        if self.coarse_target_size <= 0 or self.min_cluster_size <= 0:
            raise ValueError("cluster sizes must be positive")
        if self.max_cluster_size < self.min_cluster_size:
            raise ValueError("max_cluster_size must be >= min_cluster_size")
        if self.noise_policy not in {"fallback_topic", "unassigned"}:
            raise ValueError("noise_policy must be fallback_topic or unassigned")


@dataclass
class TopicCluster:
    cluster_id: str
    coarse_partition: str
    document_vectors: list[DocumentVector]
    noisy: bool = False
    quality_flags: list[str] = field(default_factory=list)

    @property
    def document_ids(self) -> list[str]:
        return [item.document_id for item in self.document_vectors]

    @property
    def centroid(self) -> np.ndarray:
        return np.mean(
            np.asarray([item.vector for item in self.document_vectors]), axis=0
        )

    @property
    def spread(self) -> float:
        if len(self.document_vectors) <= 1:
            return 0.0
        vectors = np.asarray([item.vector for item in self.document_vectors])
        center = np.mean(vectors, axis=0)
        return float(np.mean(np.linalg.norm(vectors - center, axis=1)))

    def preview(self, limit: int = 80) -> list[str]:
        return [
            item.document.title[:limit]
            for item in self.document_vectors
            if item.document.title
        ][:20]


@dataclass(frozen=True)
class ClusterResult:
    clusters: tuple[TopicCluster, ...]
    stats: dict


def _kmeans_labels(matrix: np.ndarray, count: int, random_state: int) -> np.ndarray:
    from sklearn.cluster import KMeans

    count = max(1, min(int(count), len(matrix)))
    if count == 1:
        return np.zeros(len(matrix), dtype=int)
    return KMeans(n_clusters=count, random_state=random_state, n_init=10).fit_predict(
        matrix
    )


def _hdbscan_labels(matrix: np.ndarray, min_cluster_size: int) -> np.ndarray:
    if len(matrix) < max(3, min_cluster_size):
        return np.zeros(len(matrix), dtype=int)
    try:
        import hdbscan

        return hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=max(2, min_cluster_size // 2),
            metric="euclidean",
            cluster_selection_method="eom",
            allow_single_cluster=True,
        ).fit_predict(matrix)
    except (ImportError, ValueError):
        # A small pilot should remain runnable when optional native wheels are
        # unavailable; the quality report records the fallback indirectly via
        # the single cluster result.
        return np.zeros(len(matrix), dtype=int)


def _split_vectors(
    items: list[DocumentVector],
    *,
    max_size: int,
    random_state: int,
    prefix: str,
) -> list[tuple[str, list[DocumentVector]]]:
    if len(items) <= max_size:
        return [(prefix, items)]
    count = math.ceil(len(items) / max_size)
    matrix = np.asarray([item.vector for item in items])
    labels = _kmeans_labels(matrix, count, random_state)
    groups: dict[int, list[DocumentVector]] = {}
    for label, item in zip(labels, items):
        groups.setdefault(int(label), []).append(item)
    output: list[tuple[str, list[DocumentVector]]] = []
    for index, group in enumerate(groups.values()):
        output.extend(
            _split_vectors(
                group,
                max_size=max_size,
                random_state=random_state + index + 1,
                prefix=f"{prefix}.{index}",
            )
        )
    return output


def _merge_small_clusters(
    clusters: list[TopicCluster],
    *,
    min_size: int,
) -> list[TopicCluster]:
    if len(clusters) <= 1:
        return clusters
    result = list(clusters)
    for source in sorted(
        list(result), key=lambda item: (len(item.document_vectors), item.cluster_id)
    ):
        if source not in result or len(source.document_vectors) >= min_size:
            continue
        targets = [
            item
            for item in result
            if item is not source and item.coarse_partition == source.coarse_partition
        ]
        if not targets:
            targets = [item for item in result if item is not source]
        if not targets:
            continue
        target = min(
            targets,
            key=lambda item: float(np.linalg.norm(source.centroid - item.centroid)),
        )
        target.document_vectors.extend(source.document_vectors)
        target.quality_flags.append("merged_small_cluster")
        result.remove(source)
    return result


def cluster_documents(
    documents: Sequence[DocumentVector],
    config: ClusterConfig | None = None,
) -> ClusterResult:
    """Run K-Means coarse partitioning followed by intra-partition HDBSCAN."""
    config = config or ClusterConfig()
    if not documents:
        return ClusterResult(
            (),
            {"documents": 0, "clusters": 0, "noise_documents": 0, "noise_ratio": 0.0},
        )
    matrix = np.asarray([item.vector for item in documents], dtype=float)
    coarse_count = max(1, math.ceil(len(documents) / config.coarse_target_size))
    coarse_labels = _kmeans_labels(matrix, coarse_count, config.random_state)
    clusters: list[TopicCluster] = []
    noise_count = 0
    for coarse_label in sorted(set(int(value) for value in coarse_labels)):
        coarse_items = [
            item
            for label, item in zip(coarse_labels, documents)
            if int(label) == coarse_label
        ]
        local_matrix = np.asarray([item.vector for item in coarse_items], dtype=float)
        local_labels = _hdbscan_labels(
            local_matrix, min(config.min_cluster_size, len(coarse_items))
        )
        groups: dict[int, list[DocumentVector]] = {}
        for label, item in zip(local_labels, coarse_items):
            groups.setdefault(int(label), []).append(item)
        for local_label, items in sorted(groups.items()):
            noisy = local_label < 0
            if noisy:
                noise_count += len(items)
                if config.noise_policy == "unassigned":
                    continue
                local_label = 999999
            clusters.append(
                TopicCluster(
                    cluster_id=f"p{coarse_label}.c{local_label}",
                    coarse_partition=f"p{coarse_label}",
                    document_vectors=items,
                    noisy=noisy,
                    quality_flags=["noise_fallback"] if noisy else [],
                )
            )

    split: list[TopicCluster] = []
    for cluster in clusters:
        for suffix, items in _split_vectors(
            cluster.document_vectors,
            max_size=config.max_cluster_size,
            random_state=config.random_state,
            prefix=cluster.cluster_id,
        ):
            split.append(
                TopicCluster(
                    cluster_id=suffix,
                    coarse_partition=cluster.coarse_partition,
                    document_vectors=items,
                    noisy=cluster.noisy,
                    quality_flags=list(cluster.quality_flags),
                )
            )
    merged = _merge_small_clusters(split, min_size=config.min_cluster_size)
    # A small-cluster merge can cross the upper target bound; split once more
    # so the final page size remains bounded without a fixed cluster count.
    bounded: list[TopicCluster] = []
    for cluster in merged:
        for suffix, items in _split_vectors(
            cluster.document_vectors,
            max_size=config.max_cluster_size,
            random_state=config.random_state,
            prefix=cluster.cluster_id,
        ):
            bounded.append(
                TopicCluster(
                    cluster_id=suffix,
                    coarse_partition=cluster.coarse_partition,
                    document_vectors=items,
                    noisy=cluster.noisy,
                    quality_flags=list(cluster.quality_flags),
                )
            )
    merged = bounded
    spreads = [cluster.spread for cluster in merged]
    median_spread = float(np.median(spreads)) if spreads else 0.0
    for cluster in merged:
        if (
            median_spread
            and cluster.spread > median_spread * config.variance_multiplier
        ):
            cluster.quality_flags.append("high_variance")
    stats = {
        "documents": len(documents),
        "coarse_partitions": coarse_count,
        "clusters": len(merged),
        "noise_documents": noise_count,
        "noise_ratio": noise_count / len(documents),
        "cluster_size_min": min(
            (len(item.document_vectors) for item in merged), default=0
        ),
        "cluster_size_max": max(
            (len(item.document_vectors) for item in merged), default=0
        ),
        "cluster_size_mean": (
            float(np.mean([len(item.document_vectors) for item in merged]))
            if merged
            else 0.0
        ),
        "quality_flagged_clusters": sum(bool(item.quality_flags) for item in merged),
        "noise_policy": config.noise_policy,
    }
    return ClusterResult(tuple(merged), stats)


@dataclass(frozen=True)
class ClusterReview:
    cluster_id: str
    keep: bool = True
    merge_with: str | None = None
    split: bool = False
    reason: str = ""


def _mapping_response(result: Any) -> dict:
    if isinstance(result, dict):
        return result
    model_dump = getattr(result, "model_dump", None)
    if callable(model_dump):
        value = model_dump()
        if isinstance(value, dict):
            return value
    text = str(getattr(result, "content", result) or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}


async def review_anomalous_clusters(
    clusters: Sequence[TopicCluster],
    *,
    reviewer: Callable[[str], Any] | Callable[[str], Awaitable[Any]] | None = None,
) -> list[ClusterReview]:
    """Ask an LLM to review only heuristic outliers.

    ``reviewer`` is injectable for tests and pilot stubs.  Without one, the
    configured compression model is used; failures keep the heuristic result
    and are intentionally non-fatal to offline index generation.
    """
    candidates = [cluster for cluster in clusters if cluster.quality_flags]
    if not candidates:
        return []
    if reviewer is None:
        try:
            from model.compression.factory import build_compression_model

            model = build_compression_model(temperature=0)
        except Exception as exc:
            return [
                ClusterReview(
                    cluster_id=cluster.cluster_id,
                    reason=f"review_unavailable:{type(exc).__name__}",
                )
                for cluster in candidates
            ]

        async def reviewer(prompt: str):
            return await model.ainvoke([{"role": "user", "content": prompt}])

    output: list[ClusterReview] = []
    semaphore = asyncio.Semaphore(8)

    async def review_one(cluster: TopicCluster) -> ClusterReview:
        async with semaphore:
            prompt = (
                "Review this topic cluster for semantic mixing. Return a concise JSON-like "
                "decision with keep, merge_with, split, and reason fields.\n"
                f"cluster_id={cluster.cluster_id}\n"
                f"flags={cluster.quality_flags}\n"
                f"titles={cluster.preview()}"
            )
            try:
                result = reviewer(prompt)
                if asyncio.iscoroutine(result):
                    result = await result
                data = _mapping_response(result)
                return ClusterReview(
                    cluster_id=cluster.cluster_id,
                    keep=bool(data.get("keep", True)),
                    merge_with=data.get("merge_with"),
                    split=bool(data.get("split", False)),
                    reason=str(data.get("reason", "")),
                )
            except Exception as exc:
                return ClusterReview(
                    cluster_id=cluster.cluster_id, reason=f"review_failed:{exc}"
                )

    output = list(
        await asyncio.gather(*(review_one(cluster) for cluster in candidates))
    )
    return output


def find_cross_partition_duplicates(
    clusters: Sequence[TopicCluster], *, threshold: float = 0.92
) -> list[tuple[TopicCluster, TopicCluster]]:
    """Find likely duplicate themes across coarse partitions for LLM review."""
    if len(clusters) < 2:
        return []
    matrix = np.asarray([cluster.centroid for cluster in clusters], dtype=float)
    try:
        from sklearn.neighbors import NearestNeighbors

        neighbors = min(8, len(clusters) - 1)
        distances, indices = (
            NearestNeighbors(n_neighbors=neighbors + 1, metric="cosine")
            .fit(matrix)
            .kneighbors(matrix)
        )
        pairs: list[tuple[TopicCluster, TopicCluster]] = []
        seen: set[tuple[int, int]] = set()
        for left_index, (row_distances, row_indices) in enumerate(
            zip(distances, indices)
        ):
            for distance, right_index in zip(row_distances[1:], row_indices[1:]):
                right_index = int(right_index)
                key = tuple(sorted((left_index, right_index)))
                if (
                    key in seen
                    or clusters[left_index].coarse_partition
                    == clusters[right_index].coarse_partition
                ):
                    continue
                seen.add(key)
                if 1.0 - float(distance) >= threshold:
                    pairs.append((clusters[left_index], clusters[right_index]))
        return pairs
    except (ImportError, ValueError):
        # Small environments without sklearn still get a correct fallback;
        # production uses the bounded nearest-neighbor path above.
        pairs = []
        for index, left in enumerate(clusters):
            for right_index in range(index + 1, len(clusters)):
                right = clusters[right_index]
                if left.coarse_partition == right.coarse_partition:
                    continue
                left_norm = float(np.linalg.norm(left.centroid))
                right_norm = float(np.linalg.norm(right.centroid))
                if (
                    left_norm
                    and right_norm
                    and float(
                        np.dot(left.centroid, right.centroid) / (left_norm * right_norm)
                    )
                    >= threshold
                ):
                    pairs.append((left, right))
        return pairs


async def review_cross_partition_duplicates(
    pairs: Sequence[tuple[TopicCluster, TopicCluster]],
    *,
    reviewer: Callable[[str], Any] | Callable[[str], Awaitable[Any]] | None = None,
) -> list[ClusterReview]:
    """Ask whether semantically similar cross-zone clusters should merge."""
    if not pairs:
        return []
    if reviewer is None:
        try:
            from model.compression.factory import build_compression_model

            model = build_compression_model(temperature=0)
        except Exception as exc:
            return [
                ClusterReview(
                    cluster_id=left.cluster_id,
                    merge_with=None,
                    reason=f"cross_zone_review_unavailable:{type(exc).__name__}",
                )
                for left, _ in pairs
            ]

        async def reviewer(prompt: str):
            return await model.ainvoke([{"role": "user", "content": prompt}])

    reviews: list[ClusterReview] = []
    semaphore = asyncio.Semaphore(8)

    async def review_one(left: TopicCluster, right: TopicCluster) -> ClusterReview:
        async with semaphore:
            prompt = (
                "Decide whether these two topic clusters are duplicate themes. "
                "Return JSON-like fields merge (boolean) and reason. Merge only if "
                "they represent the same navigational topic; otherwise keep separate.\n"
                f"left={left.cluster_id}: {left.preview()}\n"
                f"right={right.cluster_id}: {right.preview()}"
            )
            try:
                result = reviewer(prompt)
                if asyncio.iscoroutine(result):
                    result = await result
                data = _mapping_response(result)
                if not data:
                    text = str(getattr(result, "content", result)).casefold()
                    merge = '"merge": true' in text or "merge: true" in text
                    reason = text[:240]
                else:
                    merge = bool(data.get("merge", False))
                    reason = str(data.get("reason", ""))
                return ClusterReview(
                    cluster_id=left.cluster_id,
                    merge_with=right.cluster_id if merge else None,
                    reason=reason,
                )
            except Exception as exc:
                return ClusterReview(
                    cluster_id=left.cluster_id,
                    reason=f"cross_zone_review_failed:{exc}",
                )

    reviews = list(
        await asyncio.gather(*(review_one(left, right) for left, right in pairs))
    )
    return reviews


def apply_cluster_reviews(
    clusters: Sequence[TopicCluster], reviews: Sequence[ClusterReview]
) -> list[TopicCluster]:
    """Apply safe, explicit cross-cluster merge decisions."""
    result = list(clusters)
    by_id = {cluster.cluster_id: cluster for cluster in result}
    for review in reviews:
        if (
            not review.merge_with
            or review.cluster_id not in by_id
            or review.merge_with not in by_id
        ):
            continue
        source = by_id.get(review.cluster_id)
        target = by_id.get(review.merge_with)
        if source is None or target is None or source is target:
            continue
        target.document_vectors.extend(source.document_vectors)
        target.quality_flags.append("llm_merged")
        if source in result:
            result.remove(source)
        by_id.pop(source.cluster_id, None)
    return result
