import uuid
from typing import Any

from database.postgre_client import get_session
from database.rag.document import DocumentRepository
from database.rag.folder import FolderRepository
from database.rag.knowledge_base import KnowledgeBaseRepository
from database.system.dept import DeptRepository
from entity.rag.knowledge_base import KnowledgeBase
from exception.bad_except import bad_except
from utils.id import format_id
from utils.page import PageResult, build_page_result
from utils.user_context import (
    UserContext,
    is_admin,
    resolve_dept_filter,
    resolve_owner_dept,
    resolve_visible_dept_ids,
)


async def assert_kb_visible(
    kb: KnowledgeBase | None, ctx: UserContext, kb_id: object
) -> KnowledgeBase:
    """
    知识库可见性校验（数据权限收口）：visibility × ctx.data_scope 双维度判定。

    - public：任何人可见；
    - 本人库恒可见（owner 恒可见，含本人 private）；
    - department：部门边界内可见（按 data_scope 展开，all 档不限部门）；
    - private（及未知取值按最窄档处理）：仅 owner 与 admin；
    - 机器通道视为 admin。

    不可见与不存在 / 已删除 MUST 返回同一文案，不泄露资源存在性。
    供知识库、文档、文件夹链路在接受 knowledge_base_id 时统一前置调用。
    """
    if kb is None or kb.status == "deleted":
        bad_except(f"知识库不存在: {kb_id}")
    if kb.visibility == "public":
        return kb
    if kb.owner is not None and kb.owner == ctx.username:
        return kb
    if kb.visibility == "department":
        dept_ids = await resolve_visible_dept_ids(ctx)
        if dept_ids is None or kb.dept_id in dept_ids:
            return kb
        bad_except(f"知识库不存在: {kb_id}")
    # private / 未知取值：仅 owner（上方已判）与 admin
    if await is_admin(ctx):
        return kb
    bad_except(f"知识库不存在: {kb_id}")


async def assert_kb_writable(kb: KnowledgeBase, ctx: UserContext) -> None:
    """知识库写操作权限收口：仅 owner 与 admin（机器通道视为 admin）。

    供知识库元数据/删除与文档、文件夹等库内写链路统一调用；
    与可见性同文案拒绝，不泄露资源存在性。
    """
    if kb.owner is not None and kb.owner == ctx.username:
        return
    if await is_admin(ctx):
        return
    bad_except(f"知识库不存在: {kb.id.hex}")


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
        其余档位强制本人部门；知识库必须归属部门，换算结果为空
        （all 档未选部门 / 用户无部门）时拒绝创建，杜绝游离库；
        用户通道 owner 缺省为当前用户名。
        qdrant_collection 由持久层由 id 派生，不接受外部传入。
        """
        owner_dept = await resolve_owner_dept(ctx, dept_id)
        if not owner_dept:
            bad_except(
                "知识库必须归属部门：请选择归属部门，或联系管理员为当前用户配置部门"
            )
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
        列表项以当页 dept_id 批量聚合 dept_name（未归属/无对应部门为 None，零 N+1）。
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
            # 当页 dept_id（hex 非空）集合批量查部门名映射（与用户列表同模式）
            page_dept_uuids = list({uuid.UUID(kb.dept_id) for kb in kbs if kb.dept_id})
            depts = await DeptRepository(session).list_by_ids(page_dept_uuids)
            dept_name_map = {format_id(d.id): d.name for d in depts}
            enriched = []
            for kb in kbs:
                data = kb.to_dict()
                data["dept_name"] = (
                    dept_name_map.get(kb.dept_id) if kb.dept_id else None
                )
                enriched.append(data)
            return build_page_result(enriched, total, page, size)

    async def list_visible_ids(self, ctx: UserContext) -> "list[str]":
        """
        列出当前用户可检索的全部 active 知识库 id（hex 无连字符，不分页）。

        供问答链路在用户未选择知识库时解析缺省检索范围（跨库扇出，
        见 agent.tools.rag_tools.knowledge_base_search 的 knowledge_base_ids），
        为纯可见性三支并集：
        - owner 支：本人库（含本人 private）；机器通道无 username 时此支为空；
        - department 支：visibility='department' 且属本人部门边界（按 data_scope
          展开：all 不限、dept_and_child 本部门子树、dept/self 本部门）；
        - public 支：visibility='public'。
        缺省“非 private”，但上述三支例外仍可检索；他人 private 须显式选择。
        注：返回注解用字符串形式，避免类作用域内被上方 `list` 方法遮蔽。
        """
        dept_ids = await resolve_visible_dept_ids(ctx)
        async with get_session() as session:
            repo = KnowledgeBaseRepository(session)
            ids = await repo.list_active_visible_ids(
                owner=ctx.username,
                dept_ids=dept_ids,
            )
            return [format_id(kb_id) for kb_id in ids]

    async def filter_retrievable_ids(
        self, ctx: UserContext, kb_ids: "list[str]"
    ) -> "list[str]":
        """
        对显式传入的检索范围做服务端同口径过滤（可见性 × status='active' 取交集）。

        与 list_visible_ids 的三支并集（public / 本人库 / 部门 department 库）
        完全同口径，杜绝显式 kb_ids 绕过权限直达他人 private 库或已删除/
        归档库：不可见与不存在同语义，直接从结果中剔除。返回 hex 无连字符 id。
        """
        uuids: list[uuid.UUID] = []
        for hex_id in kb_ids:
            try:
                uuids.append(uuid.UUID(hex_id))
            except (ValueError, TypeError):
                continue
        if not uuids:
            return []
        dept_ids = await resolve_visible_dept_ids(ctx)
        async with get_session() as session:
            repo = KnowledgeBaseRepository(session)
            ids = await repo.list_active_visible_by_ids(
                uuids, owner=ctx.username, dept_ids=dept_ids
            )
            return [format_id(kb_id) for kb_id in ids]

    async def _assert_kb_writable(
        self, kb: KnowledgeBase, ctx: UserContext
    ) -> None:
        """写操作（元数据更新 / 删除）权限收口，实现见模块级 assert_kb_writable。"""
        await assert_kb_writable(kb, ctx)

    async def get(self, ctx: UserContext, kb_id: uuid.UUID) -> dict:
        """按 id 获取知识库（须对当前上下文可见），不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = KnowledgeBaseRepository(session)
            kb = await repo.get(kb_id)
            await assert_kb_visible(kb, ctx, kb_id)
            return kb.to_dict()

    async def update(self, ctx: UserContext, kb_id: uuid.UUID, changes: dict[str, Any]) -> dict:
        """
        仅元数据更新（name/description/icon/visibility/owner/status）；
        dept_id/qdrant_collection/embedding_* 不可变。知识库不存在时抛出业务异常；
        写权限收紧为 owner / admin（_assert_kb_writable）。
        """
        async with get_session() as session:
            repo = KnowledgeBaseRepository(session)
            kb = await repo.get(kb_id)
            await assert_kb_visible(kb, ctx, kb_id)
            await self._assert_kb_writable(kb, ctx)
            kb = await repo.update_metadata(kb_id, changes)
            if kb is None:
                bad_except(f"知识库不存在: {kb_id}")
            await session.commit()
            return kb.to_dict()

    async def delete(self, ctx: UserContext, kb_id: uuid.UUID) -> None:
        """
        带守卫的软删除：置 status='deleted'。知识库不存在 / 已删除抛出业务异常；
        库内仍存在有效文档或文件夹时拒绝删除（非空禁删，与文件夹删除守卫同模式），
        避免文档 / 分块数据游离。
        """
        async with get_session() as session:
            repo = KnowledgeBaseRepository(session)
            kb = await repo.get(kb_id)
            await assert_kb_visible(kb, ctx, kb_id)
            await self._assert_kb_writable(kb, ctx)
            if await DocumentRepository(session).has_by_kb(
                kb_id
            ) or await FolderRepository(session).has_by_kb(kb_id):
                bad_except("知识库内仍有文档或文件夹，请先清空后再删除")
            await repo.soft_delete(kb_id)
            await session.commit()
