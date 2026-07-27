"""
user_context.py - 请求级用户上下文与数据权限（data_scope）解析工具

职责：
- `get_user_context`：FastAPI 依赖。读取 `TokenAuthMiddleware` 挂载的
  `request.state.user`（JWT 通道），查询 sys_user / sys_role 构造 `UserContext`；
  静态 API key 机器通道无用户身份，等价 data_scope='all'（看全部）。
- `aggregate_data_scope`：聚合用户全部有效角色的 data_scope，取最宽档，
  供本依赖与 /auth/me 复用。
- `resolve_dept_filter`：把「上下文 + 前端请求的 dept_ids」换算为持久层可
  直接下推的过滤条件（部门 id 集合 / owner），非 all 档忽略前端参数。

档位全序（宽 → 窄）：all > dept_and_child > dept > self。
"""

import uuid
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.postgre_client import get_session
from database.system.dept import DeptRepository
from database.system.user import UserRepository
from entity.system.role import Role
from entity.system.user_role import UserRole
from exception.bad_except import bad_except
from utils.id import format_id

# 档位全序，索引越小权限越宽；未知取值按最窄处理
_SCOPE_ORDER: tuple[str, ...] = ("all", "dept_and_child", "dept", "self")

# 无任何有效角色时的缺省档位（最保守）
_DEFAULT_SCOPE = "self"


@dataclass(frozen=True)
class UserContext:
    """请求级用户上下文：机器通道 user 相关字段均为 None、data_scope='all'。"""

    user_id: str | None
    username: str | None
    dept_id: str | None  # format_id 32 位无连字符 hex；用户无部门为 None
    data_scope: str  # 'all' | 'dept_and_child' | 'dept' | 'self'
    is_machine: bool


# 机器通道（静态 API key）单例：无用户身份，看全部
MACHINE_CONTEXT = UserContext(
    user_id=None,
    username=None,
    dept_id=None,
    data_scope="all",
    is_machine=True,
)


@dataclass(frozen=True)
class DeptFilter:
    """
    持久层可直接消费的过滤条件。

    - dept_ids=None 表示不按部门过滤；[] 为空集哨兵（调用方应直接返回空结果）；
    - owner 仅 self 档非空，表示知识库按属主收敛。
    """

    dept_ids: list[str] | None
    owner: str | None = None

    @property
    def is_empty_boundary(self) -> bool:
        """边界为空集（如 dept 档用户无部门）：宁可看不见，不可看错。"""
        return self.dept_ids is not None and len(self.dept_ids) == 0


async def aggregate_data_scope(session: AsyncSession, user_id: uuid.UUID) -> str:
    """聚合用户全部 status='active' 角色的 data_scope，取最宽档；无有效角色缺省 'self'。"""
    stmt = (
        select(Role.data_scope)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id, Role.status == "active")
    )
    result = await session.execute(stmt)
    scopes = [row[0] for row in result.all()]
    if not scopes:
        return _DEFAULT_SCOPE
    # 按全序取最宽；未知取值当作最窄
    return min(
        scopes,
        key=lambda s: _SCOPE_ORDER.index(s) if s in _SCOPE_ORDER else len(_SCOPE_ORDER),
    )


async def get_user_context(request: Request) -> UserContext:
    """
    FastAPI 依赖：构造当前请求的 UserContext。

    JWT 通道按 payload.user_id 实时查库（部门/角色变更即时生效，不固化进 token）；
    对应用户已被删除时以业务失败拒绝，与 /auth/me 语义一致。
    """
    payload = getattr(request.state, "user", None)
    if payload is None:
        return MACHINE_CONTEXT

    user_id = uuid.UUID(payload["user_id"])
    async with get_session() as session:
        user = await UserRepository(session).get(user_id)
        if user is None:
            bad_except("用户不存在或已被删除")
        data_scope = await aggregate_data_scope(session, user_id)
        return UserContext(
            user_id=format_id(user.id),
            username=user.username,
            dept_id=format_id(user.dept_id),
            data_scope=data_scope,
            is_machine=False,
        )


async def resolve_dept_filter(
    ctx: UserContext,
    requested_dept_ids: list[str] | None = None,
) -> DeptFilter:
    """
    按 ctx.data_scope 把请求参数换算为持久层过滤条件：

    - all：透传前端 dept_ids（None=不过滤），跨部门浏览由前端展开子树；
    - dept_and_child：服务端以 sys_dept 展开本部门子树为边界，忽略前端参数；
    - dept：边界为本人部门，忽略前端参数；
    - self：知识库按 owner=username 收敛，不叠加部门条件。
    非 all 档且用户无部门时返回空集哨兵（列表应返回空）。
    """
    scope = ctx.data_scope
    if scope == "all":
        return DeptFilter(dept_ids=requested_dept_ids or None)
    if scope == "self":
        return DeptFilter(dept_ids=None, owner=ctx.username)
    if ctx.dept_id is None:
        return DeptFilter(dept_ids=[])
    if scope == "dept":
        return DeptFilter(dept_ids=[ctx.dept_id])
    # dept_and_child：后端展开子树（sys_dept 小表，内存 BFS）
    dept_uuid = uuid.UUID(ctx.dept_id)
    async with get_session() as session:
        descendants = await DeptRepository(session).list_descendant_ids(dept_uuid)
    return DeptFilter(dept_ids=[ctx.dept_id, *(format_id(d) for d in descendants)])
