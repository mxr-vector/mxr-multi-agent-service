import uuid

from database.postgre_client import get_session
from database.rag.folder import FolderRepository
from database.rag.knowledge_base import KnowledgeBaseRepository
from exception.bad_except import bad_except
from service.rag.knowledge_base import assert_kb_visible
from utils.page import PageResult, build_page_result
from utils.user_context import UserContext


class FolderService:
    """
    文件夹业务层。

    负责编排持久层调用与业务规则：文件夹归属知识库（创建后不可变）、
    父文件夹同库校验、扁平列表、显式 updated_at 更新，
    以及带空判定守卫的物理删除。每个方法在共享会话中开启事务并提交。
    创建/列表在接受 knowledge_base_id 时前置知识库可见性校验（数据权限收口）。
    """

    async def create(
        self,
        ctx: UserContext,
        name: str,
        knowledge_base_id: uuid.UUID,
        parent_id: uuid.UUID | None = None,
        sort_order: int = 0,
    ) -> dict:
        """
        创建文件夹并返回其数据（含数据库生成的 id）。

        校验所属知识库存在、未删除且对当前上下文可见；dept_id 从上下文注入
        （机器通道 / 无部门用户兜底空字符串）；提供 parent_id 时校验父文件夹
        存在且同属该知识库。
        """
        async with get_session() as session:
            kb_repo = KnowledgeBaseRepository(session)
            kb = await kb_repo.get(knowledge_base_id)
            await assert_kb_visible(kb, ctx, knowledge_base_id)
            repo = FolderRepository(session)
            if parent_id is not None:
                await self._require_parent_in_kb(repo, parent_id, knowledge_base_id)
            folder = await repo.create(
                name=name,
                knowledge_base_id=knowledge_base_id,
                parent_id=parent_id,
                sort_order=sort_order,
                dept_id=ctx.dept_id or "",
            )
            await session.commit()
            return folder.to_dict()

    async def list(
        self,
        ctx: UserContext,
        knowledge_base_id: uuid.UUID,
        page: int = 1,
        size: int = 20,
        parent_id: uuid.UUID | None = None,
        keyword: str | None = None,
    ) -> PageResult:
        """
        分页返回单个知识库内的扁平文件夹列表（不做服务端树装配）；
        省略 parent_id 返回该知识库全部文件夹，传入则只返回其直接子文件夹；
        可选按 keyword 对 name 过滤。知识库须对当前上下文可见。
        """
        async with get_session() as session:
            kb = await KnowledgeBaseRepository(session).get(knowledge_base_id)
            await assert_kb_visible(kb, ctx, knowledge_base_id)
            repo = FolderRepository(session)
            folders, total = await repo.list(
                knowledge_base_id=knowledge_base_id,
                page=page,
                size=size,
                parent_id=parent_id,
                keyword=keyword,
            )
            return build_page_result([f.to_dict() for f in folders], total, page, size)

    async def get(self, ctx: UserContext, folder_id: uuid.UUID) -> dict:
        """按 id 获取文件夹（须落在可见知识库下），不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = FolderRepository(session)
            folder = await repo.get(folder_id)
            if folder is None:
                bad_except(f"文件夹不存在: {folder_id}")
            await self._assert_kb(ctx, session, folder.knowledge_base_id)
            return folder.to_dict()

    async def update(
        self,
        ctx: UserContext,
        folder_id: uuid.UUID,
        name: str | None = None,
        sort_order: int | None = None,
        parent_id: uuid.UUID | None = None,
        parent_id_set: bool = False,
    ) -> dict:
        """
        更新文件夹的 name/sort_order/parent_id，不存在时抛出业务异常。
        knowledge_base_id 创建后不可变；新 parent_id 必须同属该知识库。
        """
        async with get_session() as session:
            repo = FolderRepository(session)
            folder = await repo.get(folder_id)
            if folder is None:
                bad_except(f"文件夹不存在: {folder_id}")
            await self._assert_kb(ctx, session, folder.knowledge_base_id)
            if parent_id_set and parent_id is not None:
                if parent_id == folder_id:
                    bad_except("父文件夹不能是自身")
                await self._require_parent_in_kb(
                    repo, parent_id, folder.knowledge_base_id
                )
            folder = await repo.update(
                folder_id,
                name=name,
                sort_order=sort_order,
                parent_id=parent_id,
                parent_id_set=parent_id_set,
            )
            await session.commit()
            return folder.to_dict()

    async def delete(self, ctx: UserContext, folder_id: uuid.UUID) -> None:
        """
        带守卫的物理删除：文件夹不存在抛业务异常；
        存在子文件夹或包含文档时拒绝删除，仅空文件夹才被删除。
        """
        async with get_session() as session:
            repo = FolderRepository(session)
            folder = await repo.get(folder_id)
            if folder is None:
                bad_except(f"文件夹不存在: {folder_id}")
            await self._assert_kb(ctx, session, folder.knowledge_base_id)
            if await repo.has_children(folder_id):
                bad_except("文件夹下存在子文件夹，无法删除")
            if await repo.has_referencing_document(folder_id):
                bad_except("文件夹下存在文档，无法删除")
            await repo.delete(folder_id)
            await session.commit()

    @staticmethod
    async def _require_parent_in_kb(
        repo: FolderRepository,
        parent_id: uuid.UUID,
        knowledge_base_id: uuid.UUID,
    ) -> None:
        """校验父文件夹存在且与目标同属一个知识库，否则抛业务异常。"""
        parent = await repo.get(parent_id)
        if parent is None:
            bad_except(f"父文件夹不存在: {parent_id}")
        if parent.knowledge_base_id != knowledge_base_id:
            bad_except("父文件夹与当前知识库不一致")

    @staticmethod
    async def _assert_kb(ctx, session, knowledge_base_id: uuid.UUID) -> None:
        """按 id 操作文件夹前校验其归属知识库对当前上下文可见（收口同 delete 链路）。"""
        kb = await KnowledgeBaseRepository(session).get(knowledge_base_id)
        await assert_kb_visible(kb, ctx, knowledge_base_id)
