"""
RAG 混合检索入口（模型调用）。

将 `database.qdrant_client.QdrantManager` 的混合检索（dense 语义 + sparse BM25 关键词，
服务端 RRF 融合、point id 去重）封装为返回结构化候选的函数，供 RAG 图的检索节点调用。
文档摄取（抓取 → 切分 → 写入）属于非模型调用的处理流程，见 `utils.ducument.ingest_web_pages`。

设计要点：
- 不再返回拼接字符串，而是返回结构化候选 `{point_id, text, source, score}`，
  便于图节点在 state 中携带候选元数据并最终产出 `{answer, sources[]}`；
- 候选池大小由配置驱动（ENV.rag_candidate_pool_size），本模块不关心 provider / 模型名；
- 向量化（dense/sparse）统一在 QdrantManager 内部完成。
"""

from typing import List, Optional

from database.qdrant_client import QdrantManager
from utils.ducument import RAG_COLLECTION
from utils.env import ENV


def hybrid_retrieve(query: str, pool_size: Optional[int] = None) -> List[dict]:
    """混合检索知识库，返回按融合排名去重后的结构化候选。

    - pool_size 缺省取 ENV.rag_candidate_pool_size（融合后保留的候选池上限）；
    - 每个候选为 `{point_id, text, source, score}`，score 为服务端 RRF 融合得分。
    """
    limit = pool_size if pool_size is not None else ENV.rag_candidate_pool_size
    points = QdrantManager(RAG_COLLECTION).hybrid_search(query, limit=limit)
    candidates: List[dict] = []
    for point in points:
        payload = point.payload or {}
        candidates.append(
            {
                "point_id": point.id,
                "text": payload.get("text", ""),
                "source": payload.get("source", ""),
                "score": point.score,
            }
        )
    return candidates


if __name__ == "__main__":
    # 手动冒烟测试：先经 utils.ducument.ingest_web_pages 摄取，再检索
    for candidate in hybrid_retrieve("types of reward hacking"):
        print(candidate)
