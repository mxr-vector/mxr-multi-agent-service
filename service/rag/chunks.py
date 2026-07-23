import uuid

from database.postgre_client import get_session
from database.rag.chunks import ChunkRepository
from exception.bad_except import bad_except


class ChunkService:
    """
    分块业务层（只读浏览）。

    仅提供按文档分页列出（可选 level/document_version 过滤）与按 id 获取，
    不提供任何创建/更新/删除入口——分块由文档上传流程装配与维护（见设计 D2）。
    """

    async def list(
        self,
        document_id: uuid.UUID,
        level: int | None = None,
        document_version: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """按文档分页列出分块，可选 level/document_version 过滤，按 chunk_index 升序。"""
        async with get_session() as session:
            repo = ChunkRepository(session)
            chunks = await repo.list_by_document(
                document_id,
                level=level,
                document_version=document_version,
                limit=limit,
                offset=offset,
            )
            return [chunk.to_dict() for chunk in chunks]

    async def get(self, chunk_id: uuid.UUID) -> dict:
        """按 id 获取分块，不存在时抛业务异常。"""
        async with get_session() as session:
            repo = ChunkRepository(session)
            chunk = await repo.get(chunk_id)
            if chunk is None:
                bad_except(f"分块不存在: {chunk_id}")
            return chunk.to_dict()
