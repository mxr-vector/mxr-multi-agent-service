# 类体内 `list` 方法会遮蔽内建 list，延迟注解求值以保住 list[...] 写法
from __future__ import annotations

import uuid

from database.postgre_client import get_session
from database.system.dept import DeptRepository
from database.system.role import RoleRepository
from database.system.user import UserRepository
from database.system.user_role import UserRoleRepository
from exception.bad_except import bad_except
from service.system.password import hash_password
from utils.id import format_id
from utils.page import PageResult, build_page_result


class UserService:
    """
    用户业务层。

    负责编排持久层调用与业务规则：username 全局唯一校验、
    创建/重置密码时 bcrypt 哈希（明文永不落库）、部门存在性校验、
    分配角色（校验 role_ids 全部存在后全量覆盖）。密码经 entity.to_dict
    保证不回显。每个方法在共享会话中开启事务并提交。
    """

    async def create(
        self,
        username: str,
        password: str,
        nickname: str | None = None,
        dept_id: uuid.UUID | None = None,
        email: str | None = None,
        phone: str | None = None,
        avatar: str | None = None,
        status: str = "active",
        remark: str | None = None,
    ) -> dict:
        """
        创建用户并返回其数据（不含 password）。

        username 必须全局唯一；提供 dept_id 时校验部门存在；
        明文密码在此处哈希后才进入持久层。
        """
        async with get_session() as session:
            repo = UserRepository(session)
            if await repo.get_by_username(username) is not None:
                bad_except(f"用户名已存在: {username}")
            if dept_id is not None:
                dept = await DeptRepository(session).get(dept_id)
                if dept is None:
                    bad_except(f"部门不存在: {dept_id}")
            try:
                hashed = hash_password(password)
            except ValueError as e:
                bad_except(str(e))
            user = await repo.create(
                username=username,
                password=hashed,
                nickname=nickname,
                dept_id=dept_id,
                email=email,
                phone=phone,
                avatar=avatar,
                status=status,
                remark=remark,
            )
            await session.commit()
            return user.to_dict()

    async def list(
        self,
        page: int = 1,
        size: int = 20,
        keyword: str | None = None,
        dept_ids: list[uuid.UUID] | None = None,
        status: str | None = None,
    ) -> PageResult:
        """
        真分页返回用户列表（keyword 对 username/nickname 过滤、dept_ids
        为部门子树 IN 过滤、status 精确）。列表项以当页数据批量聚合
        dept_name（无部门为 None）与 roles=[{id, name}]（无角色为空数组），
        全程无逐行查询（零 N+1）。
        """
        async with get_session() as session:
            repo = UserRepository(session)
            items, total = await repo.list(
                page=page,
                size=size,
                keyword=keyword,
                dept_ids=dept_ids,
                status=status,
            )
            # 当页 dept_id 集合批量查部门名映射
            page_dept_ids = list({i.dept_id for i in items if i.dept_id is not None})
            depts = await DeptRepository(session).list_by_ids(page_dept_ids)
            dept_name_map = {d.id: d.name for d in depts}
            # 当页 user_id 集合批量查角色关联并按用户分组
            rows = await UserRoleRepository(session).list_roles_by_user_ids(
                [i.id for i in items]
            )
            roles_map: dict[uuid.UUID, list[dict]] = {}
            for user_id, role_id, role_name in rows:
                roles_map.setdefault(user_id, []).append(
                    {"id": format_id(role_id), "name": role_name}
                )
            enriched = []
            for i in items:
                data = i.to_dict()
                data["dept_name"] = dept_name_map.get(i.dept_id) if i.dept_id else None
                data["roles"] = roles_map.get(i.id, [])
                enriched.append(data)
            return build_page_result(enriched, total, page, size)

    async def get(self, user_id: uuid.UUID) -> dict:
        """按 id 获取用户（不含 password），不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.get(user_id)
            if user is None:
                bad_except(f"用户不存在: {user_id}")
            return user.to_dict()

    async def update(
        self,
        user_id: uuid.UUID,
        username: str | None = None,
        nickname: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        avatar: str | None = None,
        status: str | None = None,
        remark: str | None = None,
        dept_id: uuid.UUID | None = None,
        dept_id_set: bool = False,
    ) -> dict:
        """
        更新用户（不含 password，密码变更走 reset_password），不存在时抛出业务异常。
        变更 username 时校验全局唯一；变更 dept_id（非置空）时校验部门存在。
        """
        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.get(user_id)
            if user is None:
                bad_except(f"用户不存在: {user_id}")
            if username is not None and username != user.username:
                existing = await repo.get_by_username(username)
                if existing is not None:
                    bad_except(f"用户名已存在: {username}")
            if dept_id_set and dept_id is not None:
                dept = await DeptRepository(session).get(dept_id)
                if dept is None:
                    bad_except(f"部门不存在: {dept_id}")
            user = await repo.update(
                user_id,
                username=username,
                nickname=nickname,
                email=email,
                phone=phone,
                avatar=avatar,
                status=status,
                remark=remark,
                dept_id=dept_id,
                dept_id_set=dept_id_set,
            )
            await session.commit()
            return user.to_dict()

    async def reset_password(self, user_id: uuid.UUID, password: str) -> None:
        """重置密码：明文在此处 bcrypt 哈希后覆盖存储，不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.get(user_id)
            if user is None:
                bad_except(f"用户不存在: {user_id}")
            try:
                hashed = hash_password(password)
            except ValueError as e:
                bad_except(str(e))
            await repo.update_password(user_id, hashed)
            await session.commit()

    async def delete(self, user_id: uuid.UUID) -> None:
        """物理删除用户，并在同一事务内清理其 user_role 关联。"""
        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.get(user_id)
            if user is None:
                bad_except(f"用户不存在: {user_id}")
            await UserRoleRepository(session).delete_by_user_id(user_id)
            await repo.delete(user_id)
            await session.commit()

    async def assign_roles(self, user_id: uuid.UUID, role_ids: list[uuid.UUID]) -> None:
        """
        分配角色（全量覆盖语义）：校验用户存在、role_ids 全部存在后，
        同一事务内先清空该用户关联再批量插入。
        """
        async with get_session() as session:
            user = await UserRepository(session).get(user_id)
            if user is None:
                bad_except(f"用户不存在: {user_id}")
            unique_ids = list(dict.fromkeys(role_ids))
            if unique_ids:
                count = await RoleRepository(session).count_existing(unique_ids)
                if count != len(unique_ids):
                    bad_except("存在无效的角色 id，分配失败")
            ur_repo = UserRoleRepository(session)
            await ur_repo.delete_by_user_id(user_id)
            if unique_ids:
                await ur_repo.add_batch(user_id, unique_ids)
            await session.commit()

    async def list_role_ids(self, user_id: uuid.UUID) -> list[str]:
        """查询用户已分配的角色 id 列表（hex 格式，供分配弹窗回显）。"""
        async with get_session() as session:
            user = await UserRepository(session).get(user_id)
            if user is None:
                bad_except(f"用户不存在: {user_id}")
            role_ids = await UserRoleRepository(session).list_role_ids_by_user(user_id)
            return [format_id(rid) for rid in role_ids]
