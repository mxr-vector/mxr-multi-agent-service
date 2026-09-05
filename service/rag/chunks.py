import uuid

from agent.constants.enums.rag import DocumentStatus
from database.postgre_client import get_session
from database.rag.chunks import ChunkRepository
from database.rag.document import DocumentRepository
from database.rag.knowledge_base import KnowledgeBaseRepository
from exception.bad_except import bad_except
from service.rag.knowledge_base import assert_kb_visible
from utils.page import PageResult, build_page_result
from utils.user_context import UserContext


class ChunkService:
    """
    分块业务层（只读浏览）。

    仅提供按文档分页列出（可选 level/document_version 过滤）与按 id 获取，
    不提供任何创建/更新/删除入口——分块由文档上传流程装配与维护（见设计 D2）。
    """

    async def list(
        self,
        ctx: UserContext,
        document_id: uuid.UUID,
        level: int | None = None,
        document_version: int | None = None,
        page: int = 1,
        size: int = 50,
    ) -> PageResult:
        """按文档分页列出分块（文档须落在可见知识库下），可选 level/document_version 过滤。"""
        async with get_session() as session:
            await self._assert_doc_visible(ctx, session, document_id)
            repo = ChunkRepository(session)
            chunks, total = await repo.list_by_document(
                document_id,
                level=level,
                document_version=document_version,
                page=page,
                size=size,
            )
            return build_page_result(
                [chunk.to_dict() for chunk in chunks], total, page, size
            )

    async def get(self, ctx: UserContext, chunk_id: uuid.UUID) -> dict:
        """按 id 获取分块（所属文档须落在可见知识库下），不存在时抛业务异常。"""
        async with get_session() as session:
            repo = ChunkRepository(session)
            chunk = await repo.get(chunk_id)
            if chunk is None:
                bad_except(f"分块不存在: {chunk_id}")
            await self._assert_doc_visible(ctx, session, chunk.document_id)
            return chunk.to_dict()

    @staticmethod
    async def _assert_doc_visible(
        ctx: UserContext, session, document_id: uuid.UUID
    ) -> None:
        """分块只读链路的可见性收口：文档须存在且其归属知识库对当前上下文可见。"""
        doc = await DocumentRepository(session).get(document_id)
        if doc is None or doc.status == DocumentStatus.DELETED:
            bad_except(f"文档不存在: {document_id}")
        kb = await KnowledgeBaseRepository(session).get(doc.knowledge_base_id)
        await assert_kb_visible(kb, ctx, doc.knowledge_base_id)
