# 类体内 `list` 方法会遮蔽内建 list，延迟注解求值以保住 list[...] 写法
from __future__ import annotations

import uuid

from database.postgre_client import get_session
from database.system.menu import MenuRepository
from database.system.role import RoleRepository
from database.system.role_menu import RoleMenuRepository
from database.system.user_role import UserRoleRepository
from exception.bad_except import bad_except
from utils.id import format_id
from utils.page import PageResult, build_page_result


class RoleService:
    """
    角色业务层。

    负责编排持久层调用与业务规则：role_key 全局唯一校验、
    删除守卫（无 user_role 关联）、分配菜单（校验 menu_ids 全部存在后
    全量覆盖）、查询角色已绑定菜单 id 列表。每个方法在共享会话中开启事务并提交。
    """

    async def create(
        self,
        name: str,
        role_key: str,
        data_scope: str = "all",
        sort_order: int = 0,
        status: str = "active",
        remark: str | None = None,
    ) -> dict:
        """创建角色并返回其数据；role_key 必须全局唯一。"""
        async with get_session() as session:
            repo = RoleRepository(session)
            if await repo.get_by_role_key(role_key) is not None:
                bad_except(f"角色标识已存在: {role_key}")
            role = await repo.create(
                name=name,
                role_key=role_key,
                data_scope=data_scope,
                sort_order=sort_order,
                status=status,
                remark=remark,
            )
            await session.commit()
            return role.to_dict()

    async def list(
        self,
        page: int = 1,
        size: int = 20,
        keyword: str | None = None,
        status: str | None = None,
    ) -> PageResult:
        """真分页返回角色列表（keyword 对 name/role_key 过滤、status 精确）。"""
        async with get_session() as session:
            repo = RoleRepository(session)
            items, total = await repo.list(
                page=page,
                size=size,
                keyword=keyword,
                status=status,
            )
            return build_page_result([i.to_dict() for i in items], total, page, size)

    async def get(self, role_id: uuid.UUID) -> dict:
        """按 id 获取角色，不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = RoleRepository(session)
            role = await repo.get(role_id)
            if role is None:
                bad_except(f"角色不存在: {role_id}")
            return role.to_dict()

    async def update(
        self,
        role_id: uuid.UUID,
        name: str | None = None,
        role_key: str | None = None,
        data_scope: str | None = None,
        sort_order: int | None = None,
        status: str | None = None,
        remark: str | None = None,
    ) -> dict:
        """更新角色，不存在时抛出业务异常。变更 role_key 时校验全局唯一。"""
        async with get_session() as session:
            repo = RoleRepository(session)
            role = await repo.get(role_id)
            if role is None:
                bad_except(f"角色不存在: {role_id}")
            if role_key is not None and role_key != role.role_key:
                existing = await repo.get_by_role_key(role_key)
                if existing is not None:
                    bad_except(f"角色标识已存在: {role_key}")
            role = await repo.update(
                role_id,
                name=name,
                role_key=role_key,
                data_scope=data_scope,
                sort_order=sort_order,
                status=status,
                remark=remark,
            )
            await session.commit()
            return role.to_dict()

    async def delete(self, role_id: uuid.UUID) -> None:
        """
        带守卫的物理删除：角色仍被用户引用（存在 user_role 关联）时拒绝删除；
        删除时同一事务内清理其 role_menu 关联。
        """
        async with get_session() as session:
            repo = RoleRepository(session)
            role = await repo.get(role_id)
            if role is None:
                bad_except(f"角色不存在: {role_id}")
            ur_count = await UserRoleRepository(session).count_by_role_id(role_id)
            if ur_count > 0:
                bad_except("角色已分配给用户，无法删除")
            await RoleMenuRepository(session).delete_by_role_id(role_id)
            await repo.delete(role_id)
            await session.commit()

    async def assign_menus(self, role_id: uuid.UUID, menu_ids: list[uuid.UUID]) -> None:
        """
        分配菜单（全量覆盖语义）：校验角色存在、menu_ids 全部存在后，
        同一事务内先清空该角色关联再批量插入。
        """
        async with get_session() as session:
            role = await RoleRepository(session).get(role_id)
            if role is None:
                bad_except(f"角色不存在: {role_id}")
            unique_ids = list(dict.fromkeys(menu_ids))
            if unique_ids:
                count = await MenuRepository(session).count_existing(unique_ids)
                if count != len(unique_ids):
                    bad_except("存在无效的菜单 id，分配失败")
            rm_repo = RoleMenuRepository(session)
            await rm_repo.delete_by_role_id(role_id)
            if unique_ids:
                await rm_repo.add_batch(role_id, unique_ids)
            await session.commit()

    async def list_menu_ids(self, role_id: uuid.UUID) -> list[str]:
        """查询角色已绑定的菜单 id 列表（hex 格式，供分配弹窗树勾选回显）。"""
        async with get_session() as session:
            role = await RoleRepository(session).get(role_id)
            if role is None:
                bad_except(f"角色不存在: {role_id}")
            menu_ids = await RoleMenuRepository(session).list_menu_ids_by_role(role_id)
            return [format_id(mid) for mid in menu_ids]
