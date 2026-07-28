import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from entity.rag.document import Document
from entity.rag.folder import Folder
from utils.page import paginate


class FolderRepository:
    """
    文件夹持久层（DAO）。

    只负责纯粹的数据访问，不含业务规则（删除守卫、同库校验等放 service 层）。
    共用 `database/postgre_client.py` 的会话，事务提交由 service 层控制。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        name: str,
        knowledge_base_id: uuid.UUID,
        parent_id: uuid.UUID | None = None,
        sort_order: int = 0,
        dept_id: str = "",
    ) -> Folder:
        """插入一条文件夹，id 由数据库 uuidv7() 生成。"""
        folder = Folder(
            name=name,
            knowledge_base_id=knowledge_base_id,
            parent_id=parent_id,
            sort_order=sort_order,
            dept_id=dept_id,
        )
        self.session.add(folder)
        await self.session.flush()
        return folder

    async def list(
        self,
        knowledge_base_id: uuid.UUID,
        page: int = 1,
        size: int = 20,
        parent_id: uuid.UUID | None = None,
        keyword: str | None = None,
    ) -> tuple[list[Folder], int]:
        """
        分页扁平列表：限定在单个知识库内；省略 parent_id 返回该知识库全部文件夹，
        传入则只返回该节点的直接子文件夹；可选按 keyword 对 name 做 ILIKE 匹配。
        返回 (items, total)。
        """
        stmt = select(Folder).where(Folder.knowledge_base_id == knowledge_base_id)
        if parent_id is not None:
            stmt = stmt.where(Folder.parent_id == parent_id)
        if keyword:
            stmt = stmt.where(Folder.name.ilike(f"%{keyword}%"))
        stmt = stmt.order_by(Folder.sort_order)
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def get(self, folder_id: uuid.UUID) -> Folder | None:
        """按 id 获取单个文件夹，不存在返回 None。"""
        return await self.session.get(Folder, folder_id)

    async def update(
        self,
        folder_id: uuid.UUID,
        name: str | None = None,
        sort_order: int | None = None,
        parent_id: uuid.UUID | None = None,
        parent_id_set: bool = False,
    ) -> Folder | None:
        """
        更新文件夹的 name/sort_order/parent_id，并显式刷新 updated_at。
        knowledge_base_id 创建后不可变，不提供更新入口。

        parent_id 允许显式置空，因此用 parent_id_set 区分“未提供”与“置为 None”。
        返回更新后的文件夹；文件夹不存在返回 None。
        """
        folder = await self.session.get(Folder, folder_id)
        if folder is None:
            return None
        if name is not None:
            folder.name = name
        if sort_order is not None:
            folder.sort_order = sort_order
        if parent_id_set:
            folder.parent_id = parent_id
        folder.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return folder

    async def delete(self, folder_id: uuid.UUID) -> None:
        """物理删除文件夹行（删除守卫在 service 层完成）。"""
        await self.session.execute(delete(Folder).where(Folder.id == folder_id))

    async def has_children(self, folder_id: uuid.UUID) -> bool:
        """是否存在以该文件夹为父的子文件夹。"""
        stmt = (
            select(func.count())
            .select_from(Folder)
            .where(Folder.parent_id == folder_id)
        )
        result = await self.session.execute(stmt)
        return (result.scalar_one() or 0) > 0

    async def has_referencing_document(self, folder_id: uuid.UUID) -> bool:
        """是否存在归属该文件夹的文档（不含已软删除的）。"""
        stmt = (
            select(func.count())
            .select_from(Document)
            .where(
                Document.folder_id == folder_id,
                Document.status != "deleted",
            )
        )
        result = await self.session.execute(stmt)
        return (result.scalar_one() or 0) > 0

    async def has_by_kb(self, knowledge_base_id: uuid.UUID) -> bool:
        """知识库下是否存在任意文件夹，供删库前置守卫。"""
        stmt = (
            select(func.count())
            .select_from(Folder)
            .where(Folder.knowledge_base_id == knowledge_base_id)
        )
        result = await self.session.execute(stmt)
        return (result.scalar_one() or 0) > 0
