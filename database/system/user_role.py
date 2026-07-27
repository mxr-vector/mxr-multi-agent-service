import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from entity.system.user_role import UserRole


class UserRoleRepository:
    """
    用户-角色关联持久层（DAO）。

    分配采用全量覆盖语义：service 层在同一事务内先 delete_by_user_id
    再 add_batch。user_id/role_id 存在性校验放 service 层。共用
    `database/postgre_client.py` 的会话，事务提交由 service 层控制。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_role_ids_by_user(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        """查询用户已分配的全部角色 id（供详情回显）。"""
        stmt = select(UserRole.role_id).where(UserRole.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_user_id(self, user_id: uuid.UUID) -> None:
        """按 user_id 清空关联（全量覆盖分配的第一步，或删除用户时清理）。"""
        await self.session.execute(delete(UserRole).where(UserRole.user_id == user_id))

    async def delete_by_role_id(self, role_id: uuid.UUID) -> None:
        """按 role_id 清空关联（删除角色时清理）。"""
        await self.session.execute(delete(UserRole).where(UserRole.role_id == role_id))

    async def add_batch(
        self,
        user_id: uuid.UUID,
        role_ids: list[uuid.UUID],
    ) -> None:
        """批量插入关联行（全量覆盖分配的第二步，与清空同一事务）。"""
        for role_id in role_ids:
            self.session.add(UserRole(user_id=user_id, role_id=role_id))
        await self.session.flush()

    async def count_by_role_id(self, role_id: uuid.UUID) -> int:
        """统计引用该角色的关联数（角色删除守卫用）。"""
        stmt = (
            select(func.count())
            .select_from(UserRole)
            .where(UserRole.role_id == role_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0
