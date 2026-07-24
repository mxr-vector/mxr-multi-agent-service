from database.postgre_client import get_session
from database.rag.stats import StatsRepository


class StatsService:
    """
    RAG 统计业务层。

    编排持久层聚合并把可能为 None 的 SUM 结果归零，返回稳定的全局概览结构。
    """

    async def overview(self) -> dict:
        """返回全局聚合：{ knowledge_base_count, document_count, total_chunk_count }。"""
        async with get_session() as session:
            repo = StatsRepository(session)
            kb_count, doc_sum, chunk_sum = await repo.overview()
            return {
                "knowledge_base_count": kb_count,
                "document_count": doc_sum or 0,
                "total_chunk_count": chunk_sum or 0,
            }
