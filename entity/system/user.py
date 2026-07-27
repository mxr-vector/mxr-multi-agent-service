import uuid
from datetime import datetime

from sqlalchemy import String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class User(Base):
    """
    用户 ORM 模型（映射 sys_user）。

    - password 只存 bcrypt 哈希（业务层负责哈希），to_dict 不含该字段，
      保证密码永不出现在任何响应中；
    - username 全局唯一；dept_id 单字段逻辑关联 sys_dept.id，
      存在性由业务层保证；
    - status 为 'active'/'disabled'，本阶段仅数据标记，不关联认证行为；
    - updated_at 由业务层在更新时显式赋值，不依赖数据库触发器。
    """

    __tablename__ = "sys_user"
    __table_args__ = {"schema": "sys"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password: Mapped[str] = mapped_column(String(100), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dept_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    email: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict:
        """转为可 JSON 序列化的普通字典（不含 password，密码永不回写）。"""
        return {
            "id": format_id(self.id),
            "username": self.username,
            "nickname": self.nickname,
            "dept_id": format_id(self.dept_id),
            "email": self.email,
            "phone": self.phone,
            "avatar": self.avatar,
            "status": self.status,
            "remark": self.remark,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
