"""
RAG 混合检索入口（模型调用）。

将 `database.qdrant_client.QdrantManager` 的混合检索（dense 语义 + sparse BM25 关键词，
服务端 RRF 融合、point id 去重）封装为返回结构化候选的函数，供 RAG 图的检索节点调用。
文档摄取（上传 → 切块 → 向量化）见 service/rag/document.py。

设计要点：
- 按 knowledge_base_id 动态定位知识库集合（经 build_kb_collection_name 派生，
  不接受外部集合名、不查 PG）；缺省时转 websearch 检索（暂未实现）；
- 不再返回拼接字符串，而是返回结构化候选
  `{point_id, text, source, score, chapter_title, document_id, chunk_id}`，
  溯源字段从 payload 宽松读取（无则归 None）；
- 候选池大小由配置驱动（ENV.rag_candidate_pool_size），本模块不关心 provider / 模型名；
- 向量化（dense/sparse）统一在 QdrantManager 内部完成。
"""

import uuid
from typing import List, Optional

from database.qdrant_client import QdrantManager, build_kb_collection_name
from utils.env import ENV
from utils.logger import logger


def web_search_retrieve(query: str, pool_size: Optional[int] = None) -> List[dict]:
    """websearch 检索：未指定知识库时的检索通道（暂未实现）。"""
    raise NotImplementedError("websearch 检索暂未实现")


def hybrid_retrieve(
    query: str,
    knowledge_base_id: Optional[uuid.UUID] = None,
    pool_size: Optional[int] = None,
) -> List[dict]:
    """混合检索知识库，返回按融合排名去重后的结构化候选。

    - knowledge_base_id 指定目标知识库：经 build_kb_collection_name 派生集合名；
      缺省时转 websearch 检索（见 web_search_retrieve，暂未实现）；
    - pool_size 缺省取 ENV.rag_candidate_pool_size（融合后保留的候选池上限）；
    - 每个候选为 `{point_id, text, source, score, chapter_title, document_id,
      chunk_id}`，score 为服务端 RRF 融合得分，溯源字段宽松读取（无则为 None）。
    """
    if knowledge_base_id is None:
        logger.info("[RAG] 未指定知识库，转 websearch 检索")
        return web_search_retrieve(query, pool_size=pool_size)

    collection = build_kb_collection_name(knowledge_base_id)
    limit = pool_size if pool_size is not None else ENV.rag_candidate_pool_size
    points = QdrantManager(collection).hybrid_search(query, limit=limit)
    candidates: List[dict] = []
    for point in points:
        payload = point.payload or {}
        candidates.append(
            {
                "point_id": point.id,
                "text": payload.get("text", ""),
                "source": payload.get("source", ""),
                "score": point.score,
                "chapter_title": payload.get("chapter_title"),
                "document_id": payload.get("document_id"),
                "chunk_id": payload.get("chunk_id"),
            }
        )
    return candidates
