import uuid
from typing import Any

from database.postgre_client import get_session
from database.rag.knowledge_base import KnowledgeBaseRepository
from entity.rag.knowledge_base import KnowledgeBase
from exception.bad_except import bad_except
from utils.page import PageResult, build_page_result
from utils.user_context import UserContext, resolve_dept_filter, resolve_owner_dept


async def assert_kb_visible(
    kb: KnowledgeBase | None, ctx: UserContext, kb_id: object
) -> KnowledgeBase:
    """
    知识库可见性校验（数据权限收口）：按 ctx.data_scope 判定单个知识库是否可见。

    不可见与不存在 / 已删除 MUST 返回同一文案，不泄露资源存在性。
    供知识库、文档、文件夹链路在接受 knowledge_base_id 时统一前置调用。
    """
    if kb is None or kb.status == "deleted":
        bad_except(f"知识库不存在: {kb_id}")
    flt = await resolve_dept_filter(ctx)
    if flt.owner is not None:
        # self 档：按属主收敛
        if kb.owner == ctx.username:
            return kb
    elif flt.dept_ids is None:
        # all 档：无边界
        return kb
    elif kb.dept_id in flt.dept_ids:
        # dept / dept_and_child 档：部门边界 IN 判定
        return kb
    bad_except(f"知识库不存在: {kb_id}")


class KnowledgeBaseService:
    """
    知识库业务层。

    负责编排持久层调用与业务规则：创建时无任何 Qdrant 副作用、
    仅元数据更新（dept_id/qdrant_collection/embedding_* 不可变，status active↔archived
    通过同一更新路径完成）、以及软删除。
    """

    async def create(
        self,
        ctx: UserContext,
        name: str,
        description: str | None = None,
        icon: str | None = None,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
        embedding_dim: int | None = None,
        visibility: str = "private",
        owner: str | None = None,
        dept_id: str | None = None,
    ) -> dict:
        """
        创建知识库（仅元数据，不创建 Qdrant collection）。
        归属部门经 resolve_owner_dept 换算：仅 all 档尊重显式 dept_id（须存在），
        其余档位强制本人部门（机器通道 / 无部门用户兜底空字符串）；
        用户通道 owner 缺省为当前用户名。
        qdrant_collection 由持久层由 id 派生，不接受外部传入。
        """
        owner_dept = await resolve_owner_dept(ctx, dept_id)
        async with get_session() as session:
            repo = KnowledgeBaseRepository(session)
            kb = await repo.create(
                name=name,
                dept_id=owner_dept,
                description=description,
                icon=icon,
                embedding_provider=embedding_provider,
                embedding_model=embedding_model,
                embedding_dim=embedding_dim,
                visibility=visibility,
                owner=owner or ctx.username,
            )
            await session.commit()
            return kb.to_dict()

    async def list(
        self,
        ctx: UserContext,
        page: int = 1,
        size: int = 20,
        keyword: str | None = None,
        dept_ids: list[str] | None = None,
    ) -> PageResult:
        """
        分页列出知识库（排除软删除的），可选按 keyword 过滤。
        部门边界由 ctx.data_scope 服务端强制：all 档尊重 dept_ids 参数，
        其余档忽略参数；空集边界直接返回空页。
        """
        flt = await resolve_dept_filter(ctx, dept_ids)
        if flt.is_empty_boundary:
            return build_page_result([], 0, page, size)
        async with get_session() as session:
            repo = KnowledgeBaseRepository(session)
            kbs, total = await repo.list(
                page=page,
                size=size,
                keyword=keyword,
                dept_ids=flt.dept_ids,
                owner=flt.owner,
            )
            return build_page_result([kb.to_dict() for kb in kbs], total, page, size)

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
        仅元数据更新（name/description/icon/visibility/owner/status）；
        dept_id/qdrant_collection/embedding_* 不可变。知识库不存在时抛出业务异常。
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
