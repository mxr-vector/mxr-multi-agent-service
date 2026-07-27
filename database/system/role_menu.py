import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from entity.system.role_menu import RoleMenu


class RoleMenuRepository:
    """
    角色-菜单关联持久层（DAO）。

    分配采用全量覆盖语义：service 层在同一事务内先 delete_by_role_id
    再 add_batch。role_id/menu_id 存在性校验放 service 层。共用
    `database/postgre_client.py` 的会话，事务提交由 service 层控制。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_menu_ids_by_role(self, role_id: uuid.UUID) -> list[uuid.UUID]:
        """查询角色已分配的全部菜单 id（供详情回显）。"""
        stmt = select(RoleMenu.menu_id).where(RoleMenu.role_id == role_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_role_id(self, role_id: uuid.UUID) -> None:
        """按 role_id 清空关联（全量覆盖分配的第一步，或删除角色时清理）。"""
        await self.session.execute(delete(RoleMenu).where(RoleMenu.role_id == role_id))

    async def delete_by_menu_id(self, menu_id: uuid.UUID) -> None:
        """按 menu_id 清空关联（删除菜单时清理）。"""
        await self.session.execute(delete(RoleMenu).where(RoleMenu.menu_id == menu_id))

    async def add_batch(
        self,
        role_id: uuid.UUID,
        menu_ids: list[uuid.UUID],
    ) -> None:
        """批量插入关联行（全量覆盖分配的第二步，与清空同一事务）。"""
        for menu_id in menu_ids:
            self.session.add(RoleMenu(role_id=role_id, menu_id=menu_id))
        await self.session.flush()

    async def count_by_menu_id(self, menu_id: uuid.UUID) -> int:
        """统计引用该菜单的关联数（菜单删除守卫用）。"""
        stmt = (
            select(func.count())
            .select_from(RoleMenu)
            .where(RoleMenu.menu_id == menu_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0
