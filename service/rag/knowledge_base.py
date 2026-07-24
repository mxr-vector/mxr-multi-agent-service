import uuid
from typing import Any

from database.postgre_client import get_session
from database.rag.knowledge_base import KnowledgeBaseRepository
from exception.bad_except import bad_except


class KnowledgeBaseService:
    """
    知识库业务层。

    负责编排持久层调用与业务规则：创建时无任何 Qdrant 副作用、
    仅元数据更新（tenant_id/qdrant_collection/embedding_* 不可变，status active↔archived
    通过同一更新路径完成）、以及软删除。
    """

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
    ) -> dict:
        """
        创建知识库（仅元数据，不创建 Qdrant collection）。
        tenant_id 缺省为 'default'，由上层从请求上下文注入。
        qdrant_collection 由持久层由 id 派生，不接受外部传入。
        """
        async with get_session() as session:
            repo = KnowledgeBaseRepository(session)
            kb = await repo.create(
                name=name,
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
            await session.commit()
            return kb.to_dict()

    async def list(self, category_id: uuid.UUID | None = None) -> list[dict]:
        """列出知识库（排除软删除的），可选按 category_id 过滤。"""
        async with get_session() as session:
            repo = KnowledgeBaseRepository(session)
            kbs = await repo.list(category_id=category_id)
            return [kb.to_dict() for kb in kbs]

    async def get(self, kb_id: uuid.UUID) -> dict:
        """按 id 获取知识库，不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = KnowledgeBaseRepository(session)
            kb = await repo.get(kb_id)
            if kb is None:
                bad_except(f"知识库不存在: {kb_id}")
            return kb.to_dict()

    async def update(self, kb_id: uuid.UUID, changes: dict[str, Any]) -> dict:
        """
        仅元数据更新（name/description/category_id/icon/visibility/owner/status）；
        tenant_id/qdrant_collection/embedding_* 不可变。知识库不存在时抛出业务异常。
        """
        async with get_session() as session:
            repo = KnowledgeBaseRepository(session)
            kb = await repo.update_metadata(kb_id, changes)
            if kb is None:
                bad_except(f"知识库不存在: {kb_id}")
            await session.commit()
            return kb.to_dict()

    async def delete(self, kb_id: uuid.UUID) -> None:
        """软删除：置 status='deleted'。知识库不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = KnowledgeBaseRepository(session)
            kb = await repo.soft_delete(kb_id)
            if kb is None:
                bad_except(f"知识库不存在: {kb_id}")
            await session.commit()
