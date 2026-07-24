import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from entity.rag.categories import Category
from entity.rag.knowledge_base import KnowledgeBase
from utils.page import paginate


class CategoryRepository:
    """
    分类持久层（DAO）。

    只负责纯粹的数据访问，不含业务规则（删除守卫等放 service 层）。
    共用 `database/postgre_client.py` 的会话，事务提交由 service 层控制。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        name: str,
        parent_id: uuid.UUID | None = None,
        sort_order: int = 0,
        tenant_id: str = "default",
    ) -> Category:
        """插入一条分类，id 由数据库 uuidv7() 生成。"""
        category = Category(
            name=name,
            parent_id=parent_id,
            sort_order=sort_order,
            tenant_id=tenant_id,
        )
        self.session.add(category)
        await self.session.flush()
        return category

    async def list(
        self,
        page: int = 1,
        size: int = 20,
        parent_id: uuid.UUID | None = None,
        keyword: str | None = None,
    ) -> tuple[list[Category], int]:
        """
        分页扁平列表：省略 parent_id 时返回全部分类，传入则只返回
        该节点的直接子分类；可选按 keyword 对 name 做 ILIKE 匹配。返回 (items, total)。
        """
        stmt = select(Category)
        if parent_id is not None:
            stmt = stmt.where(Category.parent_id == parent_id)
        if keyword:
            stmt = stmt.where(Category.name.ilike(f"%{keyword}%"))
        stmt = stmt.order_by(Category.sort_order)
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def get(self, category_id: uuid.UUID) -> Category | None:
        """按 id 获取单个分类，不存在返回 None。"""
        return await self.session.get(Category, category_id)

    async def update(
        self,
        category_id: uuid.UUID,
        name: str | None = None,
        sort_order: int | None = None,
        parent_id: uuid.UUID | None = None,
        parent_id_set: bool = False,
    ) -> Category | None:
        """
        更新分类的 name/sort_order/parent_id，并显式刷新 updated_at。

        parent_id 允许显式置空，因此用 parent_id_set 区分“未提供”与“置为 None”。
        返回更新后的分类；分类不存在返回 None。
        """
        category = await self.session.get(Category, category_id)
        if category is None:
            return None
        if name is not None:
            category.name = name
        if sort_order is not None:
            category.sort_order = sort_order
        if parent_id_set:
            category.parent_id = parent_id
        category.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return category

    async def delete(self, category_id: uuid.UUID) -> None:
        """物理删除分类行（删除守卫在 service 层完成）。"""
        await self.session.execute(delete(Category).where(Category.id == category_id))

    async def has_children(self, category_id: uuid.UUID) -> bool:
        """是否存在以该分类为父的子分类。"""
        stmt = (
            select(func.count())
            .select_from(Category)
            .where(Category.parent_id == category_id)
        )
        result = await self.session.execute(stmt)
        return (result.scalar_one() or 0) > 0

    async def has_referencing_knowledge_base(self, category_id: uuid.UUID) -> bool:
        """是否存在引用该分类的知识库（不含已软删除的）。"""
        stmt = (
            select(func.count())
            .select_from(KnowledgeBase)
            .where(
                KnowledgeBase.category_id == category_id,
                KnowledgeBase.status != "deleted",
            )
        )
        result = await self.session.execute(stmt)
        return (result.scalar_one() or 0) > 0
