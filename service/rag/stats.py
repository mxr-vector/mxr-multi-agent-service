from database.postgre_client import get_session
from database.rag.stats import StatsRepository
from utils.user_context import UserContext, resolve_dept_filter


class StatsService:
    """
    RAG 统计业务层。

    编排持久层聚合并把可能为 None 的 SUM 结果归零，返回稳定的概览结构；
    统计口径与知识库列表共用同一套 data_scope 部门边界换算。
    """

    async def overview(
        self,
        ctx: UserContext,
        dept_ids: list[str] | None = None,
    ) -> dict:
        """返回聚合概览：{ knowledge_base_count, document_count, total_chunk_count }。"""
        flt = await resolve_dept_filter(ctx, dept_ids)
        if flt.is_empty_boundary:
            return {
                "knowledge_base_count": 0,
                "document_count": 0,
                "total_chunk_count": 0,
            }
        async with get_session() as session:
            repo = StatsRepository(session)
            kb_count, doc_sum, chunk_sum = await repo.overview(
                dept_ids=flt.dept_ids, owner=flt.owner
            )
            return {
                "knowledge_base_count": kb_count,
                "document_count": doc_sum or 0,
                "total_chunk_count": chunk_sum or 0,
            }
