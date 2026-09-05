"""
RAG 混合检索入口（模型调用）。

将 `database.qdrant_client.QdrantManager` 的混合检索（dense 语义 + sparse BM25 关键词，
服务端 RRF 融合、point id 去重）封装为返回结构化候选的函数，供 RAG 图的检索节点调用。
文档摄取（上传 → 切块 → 向量化）见 service/rag/document.py。

设计要点：
- 按 knowledge_base_id 动态定位知识库集合（经 build_kb_collection_name 派生，
  不接受外部集合名、不查 PG）；跨库检索经 hybrid_retrieve_multi 对多个集合
  扇出后合并，未选库时的缺省范围（当前用户部门可见的全部知识库）由调用方
  在进图前解析为 id 列表（见 service.rag.knowledge_base
  .KnowledgeBaseService.list_visible_ids）；
- 联网搜索由 use_web_search 方法级开关显式触发（见 web_search_retrieve，
  暂未实现），与"知识库缺省"语义彻底解绑；
- 不再返回拼接字符串，而是返回结构化候选
  `{point_id, knowledge_base_id, text, source, score, chapter_title,
  document_id, chunk_id, page_start, page_end}`，其中 point_id / knowledge_base_id /
  document_id / chunk_id 均为 hex 无连字符（Qdrant 返回的 point id 经 normalize_point_id
  归一化，与 payload 内各 id 格式对齐），溯源字段从 payload 宽松读取（无则归 None）；
- 候选池大小由配置驱动（CFG.rag_candidate_pool_size），本模块不关心 provider / 模型名；
- 向量化（dense/sparse）统一在 QdrantManager 内部完成；扇出场景由本模块
  预生成一次查询向量后各集合复用。
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Sequence

from database.qdrant_client import QdrantManager, build_kb_collection_name
from core.config_snapshot import CFG
from utils.id import normalize_point_id
from utils.logger import logger

# 跨集合扇出检索的最大并发数（查询向量已预生成，单任务仅一次 Qdrant IO）
_FANOUT_MAX_WORKERS = 8


def web_search_retrieve(query: str, pool_size: Optional[int] = None) -> List[dict]:
    """联网搜索检索：由调用方经 use_web_search 方法级开关显式触发（暂未实现）。"""
    raise NotImplementedError("websearch 检索暂未实现")


def hybrid_retrieve(
    query: str,
    knowledge_base_id: uuid.UUID,
    pool_size: Optional[int] = None,
    dense_vector=None,
    sparse_vector=None,
) -> List[dict]:
    """混合检索单个知识库，返回按融合排名去重后的结构化候选。

    - knowledge_base_id 指定目标知识库：经 build_kb_collection_name 派生集合名；
    - pool_size 缺省取 CFG.rag_candidate_pool_size（融合后保留的候选池上限）；
    - dense_vector / sparse_vector 可由调用方预生成传入（扇出复用），缺省时
      由 QdrantManager 内部按 query 生成；
    - 每个候选为 `{point_id, knowledge_base_id, text, source, score,
      chapter_title, document_id, chunk_id, page_start, page_end}`，score 为服务端 RRF 融合得分，
      point_id / knowledge_base_id 为 hex 无连字符（跨库溯源与去重用），
      其余溯源字段宽松读取（无则为 None）。
    """
    collection = build_kb_collection_name(knowledge_base_id)
    limit = pool_size if pool_size is not None else CFG.rag_candidate_pool_size
    points = QdrantManager(collection).hybrid_search(
        query, limit=limit, dense_vector=dense_vector, sparse_vector=sparse_vector
    )
    candidates: List[dict] = []
    for point in points:
        payload = point.payload or {}
        candidates.append(
            {
                "point_id": normalize_point_id(point.id),
                "knowledge_base_id": knowledge_base_id.hex,
                "text": payload.get("text", ""),
                "source": payload.get("source", ""),
                "score": point.score,
                "chapter_title": payload.get("chapter_title"),
                "document_id": payload.get("document_id"),
                "chunk_id": payload.get("chunk_id"),
                "page_start": payload.get("page_start"),
                "page_end": payload.get("page_end"),
            }
        )
    return candidates


def hybrid_retrieve_multi(
    query: str,
    knowledge_base_ids: Sequence[uuid.UUID],
    pool_size: Optional[int] = None,
) -> List[dict]:
    """跨多个知识库集合扇出混合检索，合并候选并裁剪回候选池上限。

    - 查询向量（dense/sparse）只预生成一次，各集合复用后经线程池并发查询；
    - 单库检索失败（如集合尚未创建 / 未向量化）仅告警跳过，不中断整体检索；
    - 合并后按 RRF 融合得分降序裁剪到 pool_size；跨库分数为各库内排名倒数，
      可比性有限，最终相关性排序由 RAG 图的 rerank 节点统一兜底；
    - 空列表返回空候选（调用方可见知识库为空时的自然语义）。
    """
    kb_ids = list(knowledge_base_ids)
    if not kb_ids:
        logger.info("[RAG] 可检索知识库为空，返回空候选")
        return []
    limit = pool_size if pool_size is not None else CFG.rag_candidate_pool_size
    if len(kb_ids) == 1:
        # 单库同样走 _retrieve_one 的失败降级包装：单库检索失败仅告警返回空，
        # 与多库路径及上方"单库失败不中断整体检索"的语义保持一致
        return _retrieve_one_single(kb_ids[0], limit)

    # 预生成查询向量，避免扇出时每库重复调用 embedding / BM25 编码
    from model.embeddings.factory import get_embedding_client
    from model.sparse.bm25 import embed_query as sparse_embed_query

    dense_vector = get_embedding_client().embed_query(query)
    sparse_vector = sparse_embed_query(query)

    def _retrieve_one(kb_id: uuid.UUID) -> List[dict]:
        try:
            return hybrid_retrieve(
                query,
                kb_id,
                pool_size=limit,
                dense_vector=dense_vector,
                sparse_vector=sparse_vector,
            )
        except Exception as exc:
            logger.warning(f"[RAG] 知识库 {kb_id.hex} 检索失败，跳过: {exc}")
            return []

    def _retrieve_one_single(kb_id: uuid.UUID, pool_limit: int) -> List[dict]:
        try:
            return hybrid_retrieve(query, kb_id, pool_size=pool_limit)
        except Exception as exc:
            logger.warning(f"[RAG] 知识库 {kb_id.hex} 检索失败，返回空候选: {exc}")
            return []

    workers = min(_FANOUT_MAX_WORKERS, len(kb_ids))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_retrieve_one, kb_ids))

    merged = [candidate for batch in results for candidate in batch]
    merged.sort(key=lambda candidate: candidate["score"] or 0, reverse=True)
    return merged[:limit]
