import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from entity.rag.document import Document

# 仅可通过元数据更新修改的字段（内容/哈希/版本/归属/状态不在其中，见设计 D6）
_EDITABLE_FIELDS = frozenset(
    {
        "title",
        "source_uri",
        "source_system",
        "doc_type",
        "source_updated_at",
        "valid_from",
        "valid_until",
        "last_verified_at",
        "metadata",
    }
)
# 对外字段名 -> ORM 属性名（metadata 是 Python 关键字冲突，ORM 属性另命名）
_FIELD_ATTR = {"metadata": "doc_metadata"}


class DocumentRepository:
    """
    文档持久层（DAO）。

    只负责纯数据访问：插入、按 id / 来源查询、排除软删除的分页列表、
    元数据更新（显式 updated_at）、新版本内容替换与状态流转。
    不做知识库存在性、hash 比对等业务规则（由 service 层编排）。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        knowledge_base_id: uuid.UUID,
        content: str,
        content_hash: str,
        doc_type: str | None = None,
        source_uri: str | None = None,
        source_system: str | None = None,
        title: str | None = None,
        metadata: dict | None = None,
        status: str = "pending",
        version: int = 1,
    ) -> Document:
        """插入一条文档（默认 status='pending'，尚未向量化）。"""
        doc = Document(
            knowledge_base_id=knowledge_base_id,
            content=content,
            content_hash=content_hash,
            doc_type=doc_type,
            source_uri=source_uri,
            source_system=source_system,
            title=title,
            doc_metadata=metadata if metadata is not None else {},
            status=status,
            version=version,
        )
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def get(self, doc_id: uuid.UUID) -> Document | None:
        """按 id 获取文档（含软删除行，语义由业务层判断）。"""
        return await self.session.get(Document, doc_id)

    async def list_by_kb(
        self,
        knowledge_base_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Document]:
        """按知识库分页列出文档，排除 status='deleted'。"""
        stmt = (
            select(Document)
            .where(Document.knowledge_base_id == knowledge_base_id)
            .where(Document.status != "deleted")
            .order_by(Document.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_source(
        self, knowledge_base_id: uuid.UUID, source_uri: str
    ) -> Document | None:
        """
        按 (knowledge_base_id, source_uri) 找当前有效文档，用于 hash 比对。
        排除软删除，取版本最高的一条。
        """
        stmt = (
            select(Document)
            .where(Document.knowledge_base_id == knowledge_base_id)
            .where(Document.source_uri == source_uri)
            .where(Document.status != "deleted")
            .order_by(Document.version.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def update_metadata(
        self, doc_id: uuid.UUID, changes: dict[str, Any]
    ) -> Document | None:
        """
        仅更新可编辑元数据字段（忽略内容/哈希/版本/归属/状态），显式刷新 updated_at。
        文档不存在返回 None。
        """
        doc = await self.session.get(Document, doc_id)
        if doc is None:
            return None
        for field, value in changes.items():
            if field in _EDITABLE_FIELDS:
                setattr(doc, _FIELD_ATTR.get(field, field), value)
        doc.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return doc

    async def replace_content(
        self,
        doc: Document,
        content: str,
        content_hash: str,
        doc_type: str | None = None,
    ) -> Document:
        """
        新版本内容替换：version+1、替换 content/content_hash、置 status='pending'，
        显式刷新 updated_at（配合新 document_version 的 chunk 做灰度重建）。
        """
        doc.version += 1
        doc.content = content
        doc.content_hash = content_hash
        if doc_type is not None:
            doc.doc_type = doc_type
        doc.status = "pending"
        doc.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return doc

    async def set_status(self, doc: Document, status: str) -> Document:
        """状态流转（pending/reindexing/active），显式刷新 updated_at。"""
        doc.status = status
        doc.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return doc
