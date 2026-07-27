# 类体内 `list` 方法会遮蔽内建 list，延迟注解求值以保住 list[...] 写法
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from entity.system.dept import Dept
from entity.system.user import User


class DeptRepository:
    """
    部门持久层（DAO）。

    只负责纯粹的数据访问，不含业务规则（父节点存在性、防环、删除守卫
    放 service 层）。列表为扁平结构（树由前端组装），共用
    `database/postgre_client.py` 的会话，事务提交由 service 层控制。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        name: str,
        parent_id: uuid.UUID | None = None,
        sort_order: int = 0,
        leader: str | None = None,
        status: str = "active",
    ) -> Dept:
        """插入一条部门，id 由数据库 uuidv7() 生成。"""
        dept = Dept(
            name=name,
            parent_id=parent_id,
            sort_order=sort_order,
            leader=leader,
            status=status,
        )
        self.session.add(dept)
        await self.session.flush()
        return dept

    async def list(
        self,
        keyword: str | None = None,
        status: str | None = None,
    ) -> list[Dept]:
        """扁平列表（keyword 对 name 做 ILIKE、status 精确过滤），sort_order 升序，供前端组树。"""
        stmt = select(Dept)
        if keyword:
            stmt = stmt.where(Dept.name.ilike(f"%{keyword}%"))
        if status:
            stmt = stmt.where(Dept.status == status)
        stmt = stmt.order_by(Dept.sort_order)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, dept_id: uuid.UUID) -> Dept | None:
        """按 id 获取单个部门，不存在返回 None。"""
        return await self.session.get(Dept, dept_id)

    async def list_by_ids(self, dept_ids: list[uuid.UUID]) -> list[Dept]:
        """按 id 集合批量查询部门（供用户列表聚合 dept_name 映射）。"""
        if not dept_ids:
            return []
        stmt = select(Dept).where(Dept.id.in_(dept_ids))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        dept_id: uuid.UUID,
        name: str | None = None,
        sort_order: int | None = None,
        leader: str | None = None,
        status: str | None = None,
        parent_id: uuid.UUID | None = None,
        parent_id_set: bool = False,
    ) -> Dept | None:
        """
        更新部门字段，并显式刷新 updated_at；不存在返回 None。

        parent_id 允许显式置空（升为顶级部门），因此用 parent_id_set
        区分“未提供”与“置为 None”。
        """
        dept = await self.session.get(Dept, dept_id)
        if dept is None:
            return None
        if name is not None:
            dept.name = name
        if sort_order is not None:
            dept.sort_order = sort_order
        if leader is not None:
            dept.leader = leader
        if status is not None:
            dept.status = status
        if parent_id_set:
            dept.parent_id = parent_id
        dept.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return dept

    async def delete(self, dept_id: uuid.UUID) -> None:
        """物理删除部门行（删除守卫在 service 层完成）。"""
        await self.session.execute(delete(Dept).where(Dept.id == dept_id))

    async def has_children(self, dept_id: uuid.UUID) -> bool:
        """是否存在以该部门为父的子部门（删除守卫用）。"""
        stmt = select(func.count()).select_from(Dept).where(Dept.parent_id == dept_id)
        result = await self.session.execute(stmt)
        return (result.scalar_one() or 0) > 0

    async def has_referencing_user(self, dept_id: uuid.UUID) -> bool:
        """是否存在归属该部门的用户（删除守卫用）。"""
        stmt = select(func.count()).select_from(User).where(User.dept_id == dept_id)
        result = await self.session.execute(stmt)
        return (result.scalar_one() or 0) > 0

    async def list_descendant_ids(self, dept_id: uuid.UUID) -> set[uuid.UUID]:
        """
        取该部门的全部后代 id 集合（防环校验用）：内存 BFS 逐层展开，
        部门树量级小（百级），无需递归 CTE。
        """
        stmt = select(Dept.id, Dept.parent_id)
        result = await self.session.execute(stmt)
        children_map: dict[uuid.UUID | None, list[uuid.UUID]] = {}
        for row_id, row_parent in result.all():
            children_map.setdefault(row_parent, []).append(row_id)
        descendants: set[uuid.UUID] = set()
        queue = list(children_map.get(dept_id, []))
        while queue:
            current = queue.pop()
            if current in descendants:
                continue
            descendants.add(current)
            queue.extend(children_map.get(current, []))
        return descendants
