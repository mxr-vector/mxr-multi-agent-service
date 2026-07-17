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
    def batch_similarity(query_embedding: np.ndarray, embeddings: List[Dict[str, np.ndarray]]) -> List[Tuple[int, float]]:
        """
        批量计算 query 与文档向量相似度

        参数:
            query_embedding: 查询向量
            embeddings:
                [
                    {
                        "embedding": [...]
                    }
                ]

        返回:
            [
                (index, similarity)
            ]
        """

        similarities = []

        for i, item in enumerate(embeddings):
            similarity = SimilarityUtils.cosine_similarity(
                query_embedding,
                item["embedding"]
            )

            similarities.append(
                (i, similarity)
            )

        return similarities