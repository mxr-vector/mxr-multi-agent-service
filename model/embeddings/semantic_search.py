"""基于 embedding 的通用文本工具：相似度搜索、推荐、聚类与零样本分类。

这是面向调用方的通用工具类，不属于 RAG 检索链路（后者在
`agent/tools/document.py`，带知识库权限过滤与 rerank）。工具只依赖
`EmbeddingFactory` 与 numpy：文本聚类使用轻量 k-means 实现，避免为一个
可选能力引入 scikit-learn / scipy 等重依赖。
"""

from typing import Dict, List, Tuple, Union

import numpy as np

from model.embeddings.factory import EmbeddingFactory
from model.embeddings.similarity_utils import SimilarityUtils

_DEFAULT_TOP_K = 5
_DEFAULT_MAX_ITER = 100
_DEFAULT_SEED = 0


def _squared_distances(vectors: np.ndarray, centers: np.ndarray) -> np.ndarray:
    """样本到中心的平方欧氏距离（n_samples, n_clusters），内存只随 n*k 增长。"""
    distances = (
        np.sum(vectors**2, axis=1)[:, None]
        + np.sum(centers**2, axis=1)[None, :]
        - 2.0 * vectors @ centers.T
    )
    # 浮点误差可能产生极小负值，归零后再用于 argmin / 概率归一化
    return np.maximum(distances, 0.0)


def _kmeans_labels(
    vectors: np.ndarray,
    n_clusters: int,
    *,
    seed: int = _DEFAULT_SEED,
    max_iter: int = _DEFAULT_MAX_ITER,
) -> np.ndarray:
    """numpy k-means（k-means++ 初始化，固定随机种子）。

    仅用于通用工具的文本聚类；样本量级远小于训练场景，不需要 sklearn。
    """
    n_samples = vectors.shape[0]
    rng = np.random.default_rng(seed)

    centers = np.empty((n_clusters, vectors.shape[1]), dtype=vectors.dtype)
    centers[0] = vectors[rng.integers(n_samples)]
    closest_sq = _squared_distances(vectors, centers[:1]).ravel()
    for index in range(1, n_clusters):
        total = float(closest_sq.sum())
        if total <= 0:
            # 全部样本重合时无法按距离加权，退回均匀采样
            picked = int(rng.integers(n_samples))
        else:
            picked = int(rng.choice(n_samples, p=closest_sq / total))
        centers[index] = vectors[picked]
        closest_sq = np.minimum(
            closest_sq,
            _squared_distances(vectors, centers[index : index + 1]).ravel(),
        )

    labels = np.full(n_samples, -1, dtype=np.int64)
    distances = _squared_distances(vectors, centers)
    for _ in range(max_iter):
        new_labels = distances.argmin(axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for index in range(n_clusters):
            members = vectors[labels == index]
            if members.size:
                centers[index] = members.mean(axis=0)
        distances = _squared_distances(vectors, centers)
    return labels


def _as_items(value: Union[str, List[str]]) -> List[str]:
    """单字符串视为一个元素，避免按字符下标错位。"""
    return [value] if isinstance(value, str) else list(value)


class EmbeddingSearch:
    """embedding 通用工具集合（无状态，可直接静态调用）。"""

    @staticmethod
    def semantic_search(
        query: str,
        documents: Union[str, List[str]],
        top_k: int = _DEFAULT_TOP_K,
    ) -> List[Tuple[str, float]]:
        """按 embedding 余弦相似度返回与 query 最相关的文档及分数。"""
        docs = _as_items(documents)
        if not docs:
            return []
        client = EmbeddingFactory.get_client()
        query_embedding = client.embed_query(query)
        doc_embeddings = client.embed_documents(docs)
        similarities = SimilarityUtils.batch_similarity(query_embedding, doc_embeddings)
        ranked = sorted(similarities, key=lambda item: item[1], reverse=True)
        return [
            (docs[index], float(score)) for index, score in ranked[: max(1, top_k)]
        ]

    @staticmethod
    def recommend_items(
        user_history: Union[str, List[str]],
        all_items: Union[str, List[str]],
        top_k: int = 10,
    ) -> List[Tuple[str, float]]:
        """用历史偏好向量的均值对候选物品打分排序。"""
        items = _as_items(all_items)
        if not items:
            return []
        client = EmbeddingFactory.get_client()
        history_embeddings = client.embed_documents(_as_items(user_history))
        if not history_embeddings:
            return []
        user_embedding = np.mean(history_embeddings, axis=0)
        item_embeddings = client.embed_documents(items)
        similarities = SimilarityUtils.batch_similarity(user_embedding, item_embeddings)
        ranked = sorted(similarities, key=lambda item: item[1], reverse=True)
        return [
            (items[index], float(score)) for index, score in ranked[: max(1, top_k)]
        ]

    @staticmethod
    def text_cluster(
        texts: Union[str, List[str]], n_clusters: int = 2
    ) -> Dict[int, List[str]]:
        """按 embedding 距离将文本聚成指定簇数（numpy k-means）。"""
        items = _as_items(texts)
        if not items:
            return {}
        if n_clusters < 1:
            raise ValueError("n_clusters 必须为正整数")
        if n_clusters > len(items):
            raise ValueError(
                f"n_clusters({n_clusters}) 不能大于文本数量({len(items)})"
            )
        client = EmbeddingFactory.get_client()
        embeddings = np.asarray(client.embed_documents(items), dtype=np.float64)
        labels = _kmeans_labels(embeddings, n_clusters)
        clusters: Dict[int, List[str]] = {index: [] for index in range(n_clusters)}
        for text, label in zip(items, labels, strict=True):
            clusters[int(label)].append(text)
        return clusters

    @staticmethod
    def text_classify(text: str, labels: List[str]) -> Tuple[str, float]:
        """零样本分类：返回与文本最相似的标签及相似度。"""
        candidates = _as_items(labels)
        if not candidates:
            raise ValueError("labels 不能为空")
        client = EmbeddingFactory.get_client()
        text_embedding = client.embed_query(text)
        label_embeddings = client.embed_documents(candidates)
        similarities = SimilarityUtils.batch_similarity(
            text_embedding, label_embeddings
        )
        best_index, best_score = max(similarities, key=lambda item: item[1])
        return candidates[best_index], float(best_score)


if __name__ == "__main__":
    # 语义搜索 使用示例（需要可用的 embedding 服务）
    query = "如何使用Python进行数据处理?"
    documents = [
        "Python是一种流行的编程语言",
        "Python可以用于数据处理",
        "数据处理是Python的一个重要应用",
    ]
    results = EmbeddingSearch.semantic_search(query, documents)
    print(results)

    # 构建推荐系统 使用示例
    user_history = ["科幻类", "动作类", "悬疑类"]
    all_movies = ["未来世界", "太空探险", "古代战争", "浪漫之旅", "超级英雄"]
    recommendations = EmbeddingSearch.recommend_items(user_history, all_movies)
    for movie, score in recommendations:
        print(f"推荐分数: {score:.3f}, 电影: {movie}")

    # 文本聚类 使用示例
    documents_to_cluster = [
        "手机公司A发售新款手机",
        "搜索引擎公司B推出新款系统",
        "世界杯决赛阿根廷对阵法国",
        "奥运会中国队再添一金",
        "某公司发布最新AI芯片",
        "欧洲杯赛事报道",
    ]
    clusters = EmbeddingSearch.text_cluster(documents_to_cluster, n_clusters=2)
    for cluster_id, docs in clusters.items():
        print(f"--- 类别 {cluster_id} ---")
        for doc in docs:
            print(f"- {doc}")

    # 文本分类 使用示例
    text_to_classify = "这件衣服的料子很舒服，款式也好看"
    possible_labels = ["数码产品", "服装配饰", "食品饮料", "家居生活"]

    label, score = EmbeddingSearch.text_classify(text_to_classify, possible_labels)
    print(f"输入文本: '{text_to_classify}'")
    print(f"最匹配的分类是: '{label}' (相似度: {score:.3f})")
