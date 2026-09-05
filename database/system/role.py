# 类体内 `list` 方法会遮蔽内建 list，延迟注解求值以保住 list[...] 写法
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.constants.enums.system import RecordStatus
from entity.system.role import Role
from utils.page import paginate
from utils.keyword import ilike_pattern


class RoleRepository:
    """
    角色持久层（DAO）。

    只负责纯粹的数据访问，不含业务规则（role_key 唯一校验、删除守卫
    放 service 层）。共用 `database/postgre_client.py` 的会话，
    事务提交由 service 层控制。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        name: str,
        role_key: str,
        data_scope: str = "all",
        sort_order: int = 0,
        status: str = RecordStatus.ACTIVE,
        remark: str | None = None,
    ) -> Role:
        """插入一条角色，id 由数据库 uuidv7() 生成。"""
        role = Role(
            name=name,
            role_key=role_key,
            data_scope=data_scope,
            sort_order=sort_order,
            status=status,
            remark=remark,
        )
        self.session.add(role)
        await self.session.flush()
        return role

    async def list(
        self,
        page: int = 1,
        size: int = 20,
        keyword: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Role], int]:
        """
        真分页列表：服务端过滤（keyword 对 name/role_key 做 ILIKE、
        status 精确），total 为过滤后的总数。返回 (items, total)。
        """
        stmt = select(Role)
        if keyword:
            pattern = ilike_pattern(keyword)
            stmt = stmt.where(Role.name.ilike(pattern) | Role.role_key.ilike(pattern))
        if status:
            stmt = stmt.where(Role.status == status)
        stmt = stmt.order_by(Role.sort_order)
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def get(self, role_id: uuid.UUID) -> Role | None:
        """按 id 获取单个角色，不存在返回 None。"""
        return await self.session.get(Role, role_id)

    async def get_by_role_key(self, role_key: str) -> Role | None:
        """按 role_key 全局精确查询，不存在返回 None（供唯一性校验）。"""
        stmt = select(Role).where(Role.role_key == role_key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_existing(self, role_ids: list[uuid.UUID]) -> int:
        """统计给定 id 中实际存在的角色数（供分配角色时的全量存在性校验）。"""
        if not role_ids:
            return 0
        stmt = select(func.count()).select_from(Role).where(Role.id.in_(role_ids))
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0

    async def update(
        self,
        role_id: uuid.UUID,
        name: str | None = None,
        role_key: str | None = None,
        data_scope: str | None = None,
        sort_order: int | None = None,
        status: str | None = None,
        remark: str | None = None,
    ) -> Role | None:
        """更新角色字段，并显式刷新 updated_at；不存在返回 None。"""
        role = await self.session.get(Role, role_id)
        if role is None:
            return None
        if name is not None:
            role.name = name
        if role_key is not None:
            role.role_key = role_key
        if data_scope is not None:
            role.data_scope = data_scope
        if sort_order is not None:
            role.sort_order = sort_order
        if status is not None:
            role.status = status
        if remark is not None:
            role.remark = remark
        role.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return role

    async def delete(self, role_id: uuid.UUID) -> None:
        """物理删除角色行（删除守卫在 service 层完成）。"""
        await self.session.execute(delete(Role).where(Role.id == role_id))
