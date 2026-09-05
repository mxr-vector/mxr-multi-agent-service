from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.constants.enums.rag import KBStatus
from entity.rag.knowledge_base import KnowledgeBase


class StatsRepository:
    """
    RAG 统计持久层（DAO）。

    只负责纯粹的聚合读取：在排除软删除（status='deleted'）的知识库上做单条聚合，
    返回知识库数量与冗余计数之和，不做任何业务判定。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def overview(
        self,
        dept_ids: list[str] | None = None,
        owner: str | None = None,
    ) -> tuple[int, int | None, int | None]:
        """
        单条聚合：知识库数 COUNT(*)、文档数 SUM(document_count)、
        分块数 SUM(total_chunk_count)，均排除 status='deleted'；
        可选按 dept_ids IN / owner 等值收敛（口径与知识库列表一致）。

        返回 (knowledge_base_count, document_sum, chunk_sum)；无数据行时 SUM 为 None，
        由业务层归零。
        """
        stmt = select(
            func.count(),
            func.sum(KnowledgeBase.document_count),
            func.sum(KnowledgeBase.total_chunk_count),
        ).where(KnowledgeBase.status != KBStatus.DELETED)
        if dept_ids is not None:
            stmt = stmt.where(KnowledgeBase.dept_id.in_(dept_ids))
        if owner is not None:
            stmt = stmt.where(KnowledgeBase.owner == owner)
        result = await self.session.execute(stmt)
        kb_count, doc_sum, chunk_sum = result.one()
        return kb_count or 0, doc_sum, chunk_sum
