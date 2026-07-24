import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from database.qdrant_client import build_kb_collection_name
from entity.rag.knowledge_base import KnowledgeBase

# 建库后不可变、不允许通过更新修改的字段
_IMMUTABLE_FIELDS = frozenset(
    {
        "tenant_id",
        "qdrant_collection",
        "embedding_provider",
        "embedding_model",
        "embedding_dim",
    }
)
# 允许更新的元数据字段
_EDITABLE_FIELDS = frozenset(
    {"name", "description", "category_id", "icon", "visibility", "owner", "status"}
)


class KnowledgeBaseRepository:
    """
    知识库持久层（DAO）。

    只负责纯粹的数据访问：创建（仅元数据）、排除软删除的列表、按 id 获取、
    元数据更新（显式 updated_at）与软删除。不做业务规则判定。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        name: str,
        tenant_id: str = "default",
        description: str | None = None,
        category_id: uuid.UUID | None = None,
        icon: str | None = None,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
        embedding_dim: int | None = None,
        visibility: str = "private",
        owner: str | None = None,
    ) -> KnowledgeBase:
        """插入知识库（仅元数据，不创建任何 Qdrant collection）。

        应用端生成时间有序的 UUIDv7 作为 id（保持 B-tree 索引局部性、减少重排），
        并由该 id 派生 Qdrant collection 名称，对前端完全无感知。
        """
        new_id = uuid7()
        qdrant_collection = build_kb_collection_name(new_id)
        kb = KnowledgeBase(
            id=new_id,
            name=name,
            qdrant_collection=qdrant_collection,
            tenant_id=tenant_id,
            description=description,
            category_id=category_id,
            icon=icon,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
            visibility=visibility,
            owner=owner,
        )
        self.session.add(kb)
        await self.session.flush()
        return kb

    async def list(self, category_id: uuid.UUID | None = None) -> list[KnowledgeBase]:
        """列出知识库，排除 status='deleted'；可选按 category_id 过滤。"""
        stmt = select(KnowledgeBase).where(KnowledgeBase.status != "deleted")
        if category_id is not None:
            stmt = stmt.where(KnowledgeBase.category_id == category_id)
        stmt = stmt.order_by(KnowledgeBase.updated_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, kb_id: uuid.UUID) -> KnowledgeBase | None:
        """按 id 获取知识库，不存在返回 None（含软删除的行也会返回，由业务层决定语义）。"""
        return await self.session.get(KnowledgeBase, kb_id)

    async def update_metadata(
        self, kb_id: uuid.UUID, changes: dict[str, Any]
    ) -> KnowledgeBase | None:
        """
        仅更新可编辑元数据字段（忽略不可变字段），并显式刷新 updated_at。
        知识库不存在返回 None。
        """
        kb = await self.session.get(KnowledgeBase, kb_id)
        if kb is None:
            return None
        for field, value in changes.items():
            if field in _EDITABLE_FIELDS:
                setattr(kb, field, value)
        kb.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return kb

    async def soft_delete(self, kb_id: uuid.UUID) -> KnowledgeBase | None:
        """软删除：设置 status='deleted' 并刷新 updated_at；不存在返回 None。"""
        kb = await self.session.get(KnowledgeBase, kb_id)
        if kb is None:
            return None
        kb.status = "deleted"
        kb.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return kb

    async def adjust_counts(
        self, kb: KnowledgeBase, doc_delta: int = 0, chunk_delta: int = 0
    ) -> KnowledgeBase:
        """
        增量调整冗余计数（document_count / total_chunk_count），并刷新 updated_at。

        由业务层在写入文档/块的同一事务内调用，保持计数与实际行数一致；
        计数不允许为负，下溢时归零。
        """
        kb.document_count = max(0, kb.document_count + doc_delta)
        kb.total_chunk_count = max(0, kb.total_chunk_count + chunk_delta)
        kb.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return kb
