from typing import List, Tuple

import numpy as np


class SimilarityUtils:
    """
    向量相似度计算工具
    """

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """
        计算余弦相似度

        参数:
            a: query 向量
            b: 文档向量

        返回:
            float 相似度
        """
        a = np.asarray(a)
        b = np.asarray(b)

        denominator = np.linalg.norm(a) * np.linalg.norm(b)

        if denominator == 0:
            return 0.0

        return np.dot(a, b) / denominator


    @staticmethod
    def batch_similarity(query_embedding: np.ndarray, embeddings: List[List[float]]) -> List[Tuple[int, float]]:
        """
        批量计算 query 与文档向量相似度

        参数:
            query_embedding: 查询向量
            embeddings: 标准化后的纯向量列表
                [
                    [...],
                    [...]
                ]

        返回:
            [
                (index, similarity)
            ]
        """

        similarities = []

        for i, vector in enumerate(embeddings):
            similarity = SimilarityUtils.cosine_similarity(
                query_embedding,
                vector
            )

            similarities.append(
                (i, similarity)
            )

        return similarities