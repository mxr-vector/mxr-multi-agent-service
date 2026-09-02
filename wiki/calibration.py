"""Offline parameter calibration helpers for million-document topic indexes."""

from __future__ import annotations

from dataclasses import asdict
from itertools import product
from typing import Iterable, Sequence

from wiki.clustering import ClusterConfig, cluster_documents
from wiki.vectors import DocumentVector


def _score(stats: dict, *, target_min: int, target_max: int) -> float:
    """Higher is better: prefer target-sized clusters and low noise/flags."""
    mean_size = float(stats.get("cluster_size_mean") or 0)
    size_penalty = 0.0
    if mean_size < target_min:
        size_penalty = (target_min - mean_size) / target_min
    elif mean_size > target_max:
        size_penalty = (mean_size - target_max) / target_max
    noise_penalty = float(stats.get("noise_ratio") or 0)
    flag_penalty = float(stats.get("quality_flagged_clusters") or 0) / max(
        1, int(stats.get("clusters") or 1)
    )
    return 1.0 - min(1.0, size_penalty + noise_penalty + flag_penalty)


def calibrate_cluster_parameters(
    document_vectors: Sequence[DocumentVector],
    *,
    coarse_target_sizes: Iterable[int] = (250, 500, 750),
    min_cluster_sizes: Iterable[int] = (10, 20, 30),
    max_cluster_size: int = 100,
    target_min: int = 20,
    target_max: int = 100,
) -> dict:
    """Evaluate a bounded grid and return ranked configurations.

    This function is deliberately vector-only: a million-document calibration
    can sample precomputed vectors without invoking the embedding service or
    the LLM page generator.
    """
    trials = []
    for coarse_target, minimum in product(coarse_target_sizes, min_cluster_sizes):
        config = ClusterConfig(
            coarse_target_size=int(coarse_target),
            min_cluster_size=int(minimum),
            max_cluster_size=max_cluster_size,
        )
        result = cluster_documents(document_vectors, config)
        trials.append(
            {
                "config": asdict(config),
                "stats": result.stats,
                "score": _score(
                    result.stats, target_min=target_min, target_max=target_max
                ),
            }
        )
    trials.sort(
        key=lambda item: (
            -item["score"],
            item["config"]["coarse_target_size"],
            item["config"]["min_cluster_size"],
        )
    )
    return {
        "documents": len(document_vectors),
        "trials": trials,
        "recommended": trials[0]["config"] if trials else None,
    }
