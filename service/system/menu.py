import uuid

from database.postgre_client import get_session
from database.system.menu import MenuRepository
from database.system.role_menu import RoleMenuRepository
from exception.bad_except import bad_except

# 允许的菜单类型：dir 目录（仅组织层级）、menu 页面菜单、button 按钮权限项
_MENU_TYPES = {"dir", "menu", "button"}


class MenuService:
    """
    菜单业务层。

    负责编排持久层调用与业务规则：menu_type 枚举校验（dir/menu/button）、
    父节点存在性校验、防环校验（新父非自身/后代）、删除守卫
    （无子菜单且无 role_menu 绑定）。列表为扁平结构（树由前端组装），
    每个方法在共享会话中开启事务并提交。
    """

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
    ) -> dict:
        """创建菜单并返回其数据；校验 menu_type 合法、父节点存在。"""
        if menu_type not in _MENU_TYPES:
            bad_except(f"非法的菜单类型: {menu_type}（应为 dir/menu/button）")
        async with get_session() as session:
            repo = MenuRepository(session)
            if parent_id is not None:
                parent = await repo.get(parent_id)
                if parent is None:
                    bad_except(f"父菜单不存在: {parent_id}")
            menu = await repo.create(
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
            await session.commit()
            return menu.to_dict()

    async def list(
        self,
        keyword: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """扁平列表（sort_order 升序），供前端组树。"""
        async with get_session() as session:
            repo = MenuRepository(session)
            menus = await repo.list(keyword=keyword, status=status)
            return [m.to_dict() for m in menus]

    async def get(self, menu_id: uuid.UUID) -> dict:
        """按 id 获取菜单，不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = MenuRepository(session)
            menu = await repo.get(menu_id)
            if menu is None:
                bad_except(f"菜单不存在: {menu_id}")
            return menu.to_dict()

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
    ) -> dict:
        """
        更新菜单（menu_type 创建后不可变），不存在时抛出业务异常。

        变更 parent_id 时校验：父菜单存在、不是自身、也不是自身的后代
        （防环，用内存 BFS 后代集合判断）。
        """
        async with get_session() as session:
            repo = MenuRepository(session)
            menu = await repo.get(menu_id)
            if menu is None:
                bad_except(f"菜单不存在: {menu_id}")
            if parent_id_set and parent_id is not None:
                if parent_id == menu_id:
                    bad_except("父菜单不能是自身")
                parent = await repo.get(parent_id)
                if parent is None:
                    bad_except(f"父菜单不存在: {parent_id}")
                descendants = await repo.list_descendant_ids(menu_id)
                if parent_id in descendants:
                    bad_except("父菜单不能是自身的下级菜单")
            menu = await repo.update(
                menu_id,
                label=label,
                name=name,
                path=path,
                component=component,
                icon=icon,
                perms=perms,
                visible=visible,
                sort_order=sort_order,
                status=status,
                parent_id=parent_id,
                parent_id_set=parent_id_set,
            )
            await session.commit()
            return menu.to_dict()

    async def delete(self, menu_id: uuid.UUID) -> None:
        """带守卫的物理删除：存在子菜单或仍被角色绑定（role_menu）时拒绝删除。"""
        async with get_session() as session:
            repo = MenuRepository(session)
            menu = await repo.get(menu_id)
            if menu is None:
                bad_except(f"菜单不存在: {menu_id}")
            if await repo.has_children(menu_id):
                bad_except("菜单下存在子菜单，无法删除")
            rm_count = await RoleMenuRepository(session).count_by_menu_id(menu_id)
            if rm_count > 0:
                bad_except("菜单已被角色绑定，无法删除")
            await repo.delete(menu_id)
            await session.commit()
