import uuid

from database.postgre_client import get_session
from database.rag.categories import CategoryRepository
from exception.bad_except import bad_except


class CategoryService:
    """
    分类业务层。

    负责编排持久层调用与业务规则：扁平列表、显式 updated_at 更新，
    以及带空判定守卫的物理删除。每个方法在共享会话中开启事务并提交。
    """

    async def create(
        self,
        name: str,
        parent_id: uuid.UUID | None = None,
        sort_order: int = 0,
        tenant_id: str = "default",
    ) -> dict:
        """创建分类并返回其数据（含数据库生成的 id；tenant_id 缺省 'default'）。"""
        async with get_session() as session:
            repo = CategoryRepository(session)
            category = await repo.create(
                name=name,
                parent_id=parent_id,
                sort_order=sort_order,
                tenant_id=tenant_id,
            )
            await session.commit()
            return category.to_dict()

    async def list(self, parent_id: uuid.UUID | None = None) -> list[dict]:
        """
        返回扁平分类列表（不做服务端树装配）；
        省略 parent_id 返回全部，传入则只返回其直接子分类。
        """
        async with get_session() as session:
            repo = CategoryRepository(session)
            categories = await repo.list(parent_id=parent_id)
            return [c.to_dict() for c in categories]

    async def get(self, category_id: uuid.UUID) -> dict:
        """按 id 获取分类，不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = CategoryRepository(session)
            category = await repo.get(category_id)
            if category is None:
                bad_except(f"分类不存在: {category_id}")
            return category.to_dict()

    async def update(
        self,
        category_id: uuid.UUID,
        name: str | None = None,
        sort_order: int | None = None,
        parent_id: uuid.UUID | None = None,
        parent_id_set: bool = False,
    ) -> dict:
        """更新分类的 name/sort_order/parent_id，不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = CategoryRepository(session)
            category = await repo.update(
                category_id,
                name=name,
                sort_order=sort_order,
                parent_id=parent_id,
                parent_id_set=parent_id_set,
            )
            if category is None:
                bad_except(f"分类不存在: {category_id}")
            await session.commit()
            return category.to_dict()

    async def delete(self, category_id: uuid.UUID) -> None:
        """
        带守卫的物理删除：分类不存在抛业务异常；
        存在子分类或被知识库引用时拒绝删除，仅空分类才被删除。
        """
        async with get_session() as session:
            repo = CategoryRepository(session)
            category = await repo.get(category_id)
            if category is None:
                bad_except(f"分类不存在: {category_id}")
            if await repo.has_children(category_id):
                bad_except("分类下存在子分类，无法删除")
            if await repo.has_referencing_knowledge_base(category_id):
                bad_except("分类已被知识库引用，无法删除")
            await repo.delete(category_id)
            await session.commit()
