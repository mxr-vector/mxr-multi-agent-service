import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from entity.rag.chunks import Chunk
from utils.page import paginate


class ChunkRepository:
    """
    父子块持久层（DAO）。

    只读浏览 + 写入/删除的纯数据访问：批量插入一批块、按文档分页列出
    （可选 level/document_version 过滤，按 chunk_index 排序）、按 id 获取、
    取某版本的 level 0 叶块（供向量化）、按 (document_id, document_version) 删除。
    父子引用（parent_chunk_id）由业务层在插入前装配。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_insert(self, chunks: list[Chunk]) -> list[Chunk]:
        """批量插入一批块并 flush（服务端生成 id）。"""
        if not chunks:
            return []
        self.session.add_all(chunks)
        await self.session.flush()
        return chunks

    async def list_by_document(
        self,
        document_id: uuid.UUID,
        level: int | None = None,
        document_version: int | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[Chunk], int]:
        """按文档分页列出块，可选 level/document_version 过滤，按 chunk_index 升序。返回 (items, total)。"""
        stmt = select(Chunk).where(Chunk.document_id == document_id)
        if level is not None:
            stmt = stmt.where(Chunk.level == level)
        if document_version is not None:
            stmt = stmt.where(Chunk.document_version == document_version)
        stmt = stmt.order_by(Chunk.chunk_index.asc())
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def get(self, chunk_id: uuid.UUID) -> Chunk | None:
        """按 id 获取块，不存在返回 None。"""
        return await self.session.get(Chunk, chunk_id)

    async def fetch_level0(
        self, document_id: uuid.UUID, document_version: int
    ) -> list[Chunk]:
        """取某文档指定版本的全部 level 0 叶块（供向量化），按 chunk_index 升序。"""
        stmt = (
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .where(Chunk.document_version == document_version)
            .where(Chunk.level == 0)
            .order_by(Chunk.chunk_index.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_version(
        self, document_id: uuid.UUID, document_version: int
    ) -> None:
        """删除某文档指定版本的全部块（灰度重建时清理旧版本）。"""
        stmt = (
            delete(Chunk)
            .where(Chunk.document_id == document_id)
            .where(Chunk.document_version == document_version)
        )
        await self.session.execute(stmt)

    async def fetch_level0_excluding_version(
        self, document_id: uuid.UUID, keep_version: int
    ) -> list[Chunk]:
        """取某文档除 keep_version 外其余版本的 level 0 叶块（供清理旧 Qdrant 点）。"""
        stmt = (
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .where(Chunk.document_version != keep_version)
            .where(Chunk.level == 0)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_excluding_version(
        self, document_id: uuid.UUID, keep_version: int
    ) -> None:
        """删除某文档除 keep_version 外其余版本的全部块（新点写入后清理）。"""
        stmt = (
            delete(Chunk)
            .where(Chunk.document_id == document_id)
            .where(Chunk.document_version != keep_version)
        )
        await self.session.execute(stmt)

    async def fetch_level0_all(self, document_id: uuid.UUID) -> list[Chunk]:
        """取某文档全部版本的 level 0 叶块（供删除文档时收集 Qdrant point id）。"""
        stmt = (
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .where(Chunk.level == 0)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_document(self, document_id: uuid.UUID) -> None:
        """删除某文档全部版本的全部块（删除文档时一次清干净）。"""
        stmt = delete(Chunk).where(Chunk.document_id == document_id)
        await self.session.execute(stmt)

    async def count_level0(self, document_id: uuid.UUID, document_version: int) -> int:
        """统计某文档指定版本的 level 0 叶块数量（用于计数同步）。"""
        chunks = await self.fetch_level0(document_id, document_version)
        return len(chunks)

    @staticmethod
    def build_chunk(
        document_id: uuid.UUID,
        document_version: int,
        level: int,
        chunk_index: int,
        content: str,
        parent_chunk_id: uuid.UUID | None = None,
        char_start: int | None = None,
        char_end: int | None = None,
        chapter_title: str | None = None,
        page_start: int | None = None,
        page_end: int | None = None,
        content_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
        dept_id: str = "",
    ) -> Chunk:
        """构造一个未落库的 Chunk 实例，供业务层装配父子引用后批量插入。"""
        return Chunk(
            document_id=document_id,
            document_version=document_version,
            level=level,
            chunk_index=chunk_index,
            content=content,
            parent_chunk_id=parent_chunk_id,
            char_start=char_start,
            char_end=char_end,
            chapter_title=chapter_title,
            page_start=page_start,
            page_end=page_end,
            content_hash=content_hash,
            chunk_metadata=metadata if metadata is not None else {},
            dept_id=dept_id,
        )
