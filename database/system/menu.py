# 类体内 `list` 方法会遮蔽内建 list，延迟注解求值以保住 list[...] 写法
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from entity.system.menu import Menu

from utils.keyword import ilike_pattern


class MenuRepository:
    """
    菜单持久层（DAO）。

    只负责纯粹的数据访问，不含业务规则（menu_type 校验、父节点存在性、
    防环、删除守卫放 service 层）。列表为扁平结构（树由前端组装），
    共用 `database/postgre_client.py` 的会话，事务提交由 service 层控制。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        menu_type: str,
        label: str,
        parent_id: uuid.UUID | None = None,
        name: str | None = None,
        path: str | None = None,
        component: str | None = None,
        icon: str | None = None,
        perms: str | None = None,
        visible: bool = True,
        sort_order: int = 0,
        status: str = "active",
    ) -> Menu:
        """插入一条菜单，id 由数据库 uuidv7() 生成。"""
        menu = Menu(
            menu_type=menu_type,
            label=label,
            parent_id=parent_id,
            name=name,
            path=path,
            component=component,
            icon=icon,
            perms=perms,
            visible=visible,
            sort_order=sort_order,
            status=status,
        )
        self.session.add(menu)
        await self.session.flush()
        return menu

    async def list(
        self,
        keyword: str | None = None,
        status: str | None = None,
    ) -> list[Menu]:
        """扁平列表（keyword 对 label 做 ILIKE、status 精确过滤），sort_order 升序，供前端组树。"""
        stmt = select(Menu)
        if keyword:
            stmt = stmt.where(Menu.label.ilike(ilike_pattern(keyword)))
        if status:
            stmt = stmt.where(Menu.status == status)
        stmt = stmt.order_by(Menu.sort_order)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, menu_id: uuid.UUID) -> Menu | None:
        """按 id 获取单个菜单，不存在返回 None。"""
        return await self.session.get(Menu, menu_id)

    async def count_existing(self, menu_ids: list[uuid.UUID]) -> int:
        """统计给定 id 中实际存在的菜单数（供分配菜单时的全量存在性校验）。"""
        if not menu_ids:
            return 0
        stmt = select(func.count()).select_from(Menu).where(Menu.id.in_(menu_ids))
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0

    async def update(
        self,
        menu_id: uuid.UUID,
        label: str | None = None,
        name: str | None = None,
        path: str | None = None,
        component: str | None = None,
        icon: str | None = None,
        perms: str | None = None,
        visible: bool | None = None,
        sort_order: int | None = None,
        status: str | None = None,
        parent_id: uuid.UUID | None = None,
        parent_id_set: bool = False,
    ) -> Menu | None:
        """
        更新菜单字段（menu_type 创建后不可变），并显式刷新 updated_at；
        不存在返回 None。

        parent_id 允许显式置空（升为顶级节点），因此用 parent_id_set
        区分“未提供”与“置为 None”。
        """
        menu = await self.session.get(Menu, menu_id)
        if menu is None:
            return None
        if label is not None:
            menu.label = label
        if name is not None:
            menu.name = name
        if path is not None:
            menu.path = path
        if component is not None:
            menu.component = component
        if icon is not None:
            menu.icon = icon
        if perms is not None:
            menu.perms = perms
        if visible is not None:
            menu.visible = visible
        if sort_order is not None:
            menu.sort_order = sort_order
        if status is not None:
            menu.status = status
        if parent_id_set:
            menu.parent_id = parent_id
        menu.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return menu

    async def delete(self, menu_id: uuid.UUID) -> None:
        """物理删除菜单行（删除守卫在 service 层完成）。"""
        await self.session.execute(delete(Menu).where(Menu.id == menu_id))

    async def has_children(self, menu_id: uuid.UUID) -> bool:
        """是否存在以该菜单为父的子节点（删除守卫用）。"""
        stmt = select(func.count()).select_from(Menu).where(Menu.parent_id == menu_id)
        result = await self.session.execute(stmt)
        return (result.scalar_one() or 0) > 0

    async def list_descendant_ids(self, menu_id: uuid.UUID) -> set[uuid.UUID]:
        """
        取该菜单的全部后代 id 集合（防环校验用）：内存 BFS 逐层展开，
        菜单树量级小（百级），无需递归 CTE。
        """
        stmt = select(Menu.id, Menu.parent_id)
        result = await self.session.execute(stmt)
        children_map: dict[uuid.UUID | None, list[uuid.UUID]] = {}
        for row_id, row_parent in result.all():
            children_map.setdefault(row_parent, []).append(row_id)
        descendants: set[uuid.UUID] = set()
        queue = list(children_map.get(menu_id, []))
        while queue:
            current = queue.pop()
            if current in descendants:
                continue
            descendants.add(current)
            queue.extend(children_map.get(current, []))
        return descendants
