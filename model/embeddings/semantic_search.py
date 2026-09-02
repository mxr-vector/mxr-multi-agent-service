from typing import List, Union

import numpy as np

from model.embeddings.factory import EmbeddingFactory
from model.embeddings.similarity_utils import SimilarityUtils


class EmbeddingSearch:
    @staticmethod
    def semantic_search(query: str, documents: Union[str, List[str]], top_k=5):
        """语义搜索"""
        client = EmbeddingFactory.get_client()
        # 生成查询向量
        query_embedding = client.embed_query(query)
        # 生成文档向量
        doc_embeddings = client.embed_documents(documents)
        # 计算相似度
        similaritys = SimilarityUtils.batch_similarity(query_embedding, doc_embeddings)

        sorted_similaritys = sorted(similaritys, key=lambda x: x[1], reverse=True)
        return [(documents[i], sim) for i, sim in sorted_similaritys[:top_k]]

    @staticmethod
    def recommend_items(
        user_history: Union[str, List[str]], all_items: Union[str, List[str]], top_k=10
    ):
        """构建推荐系统"""
        client = EmbeddingFactory.get_client()
        # 生成用户历史向量
        history_embeddings = client.embed_documents(user_history)
        user_embedding = np.mean(history_embeddings, axis=0)
        # 生成所有物品向量
        items_embeddings = client.embed_documents(all_items)
        # 计算相似度
        similaritys = SimilarityUtils.batch_similarity(user_embedding, items_embeddings)
        sorted_similaritys = sorted(similaritys, key=lambda x: x[1], reverse=True)
        return [(all_items[i], sim) for i, sim in sorted_similaritys[:top_k]]

    @staticmethod
    def text_cluster(texts: List[str], n_clusters=2):
        """将一组文本进行聚类"""
        client = EmbeddingFactory.get_client()
        text_embeddings = client.embed_documents(texts)
        embeddings = np.array(text_embeddings)
        # 2. 使用KMeans算法进行聚类
        from sklearn.cluster import KMeans

        kmeans = KMeans(n_clusters=n_clusters, random_state=0, n_init="auto").fit(
            embeddings
        )
        # 3. 整理并返回结果
        clusters = {i: [] for i in range(n_clusters)}
        for i, label in enumerate(kmeans.labels_):
            clusters[label].append(texts[i])
        return clusters

    @staticmethod
    def text_classify(text: str, labels: List[str]):
        """零样本文本分类"""
        client = EmbeddingFactory.get_client()
        text_embedding = client.embed_query(text)
        labels_embeddings = client.embed_documents(labels)
        similaritys = SimilarityUtils.batch_similarity(
            text_embedding, labels_embeddings
        )

        best_match_index = max(range(len(similaritys)), key=lambda i: similaritys[i][1])
        return labels[best_match_index], similaritys[best_match_index][1]


if __name__ == "__main__":
    # 语义搜索 使用示例
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
