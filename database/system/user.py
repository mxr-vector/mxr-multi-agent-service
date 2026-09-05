import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from entity.system.user import User
from utils.page import paginate
from utils.keyword import ilike_pattern


class UserRepository:
    """
    用户持久层（DAO）。

    只负责纯粹的数据访问，不含业务规则（用户名唯一校验、密码哈希、
    部门存在性校验放 service 层）。password 只在写路径经过本层，
    读路径由 entity.to_dict 保证不回写。共用 `database/postgre_client.py`
    的会话，事务提交由 service 层控制。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
    ) -> User:
        """插入一条用户（password 为 service 层算好的 bcrypt 哈希），id 由数据库 uuidv7() 生成。"""
        user = User(
            username=username,
            password=password,
            nickname=nickname,
            dept_id=dept_id,
            email=email,
            phone=phone,
            avatar=avatar,
            status=status,
            remark=remark,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def list(
        self,
        page: int = 1,
        size: int = 20,
        keyword: str | None = None,
        dept_ids: list[uuid.UUID] | None = None,
        status: str | None = None,
    ) -> tuple[list[User], int]:
        """
        真分页列表：服务端过滤（keyword 对 username/nickname 做 ILIKE、
        dept_ids 为 IN 集合过滤（部门子树）、status 精确），total 为过滤后
        的总数。返回 (items, total)。
        """
        stmt = select(User)
        if keyword:
            pattern = ilike_pattern(keyword)
            stmt = stmt.where(
                User.username.ilike(pattern) | User.nickname.ilike(pattern)
            )
        if dept_ids:
            stmt = stmt.where(User.dept_id.in_(dept_ids))
        if status:
            stmt = stmt.where(User.status == status)
        stmt = stmt.order_by(User.created_at.desc())
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def get(self, user_id: uuid.UUID) -> User | None:
        """按 id 获取单个用户，不存在返回 None。"""
        return await self.session.get(User, user_id)

    async def get_by_username(self, username: str) -> User | None:
        """按 username 全局精确查询，不存在返回 None（供唯一性校验）。"""
        stmt = select(User).where(User.username == username)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

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
    ) -> User | None:
        """
        更新用户字段（不含 password，密码变更走 update_password），
        并显式刷新 updated_at；不存在返回 None。

        dept_id 允许显式置空（移出部门），因此用 dept_id_set 区分
        “未提供”与“置为 None”。
        """
        user = await self.session.get(User, user_id)
        if user is None:
            return None
        if username is not None:
            user.username = username
        if nickname is not None:
            user.nickname = nickname
        if email is not None:
            user.email = email
        if phone is not None:
            user.phone = phone
        if avatar is not None:
            user.avatar = avatar
        if status is not None:
            user.status = status
        if remark is not None:
            user.remark = remark
        if dept_id_set:
            user.dept_id = dept_id
        user.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return user

    async def update_password(
        self, user_id: uuid.UUID, hashed_password: str
    ) -> User | None:
        """重置密码专用：覆盖 bcrypt 哈希并刷新 updated_at；不存在返回 None。"""
        user = await self.session.get(User, user_id)
        if user is None:
            return None
        user.password = hashed_password
        user.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return user

    async def delete(self, user_id: uuid.UUID) -> None:
        """物理删除用户行（关联清理在 service 层编排）。"""
        await self.session.execute(delete(User).where(User.id == user_id))
