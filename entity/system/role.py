import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class Role(Base):
    """
    角色 ORM 模型（映射 sys_role）。

    - role_key 为角色权限键（如 'admin'），全局唯一；
    - data_scope 本阶段仅存储，不参与数据过滤（后续数据权限 change 消费）；
    - updated_at 由业务层在更新时显式赋值，不依赖数据库触发器。
    """

    __tablename__ = "sys_role"
    __table_args__ = {"schema": "sys"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role_key: Mapped[str] = mapped_column(String(100), nullable=False)
    data_scope: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'all'")
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
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
        """转为可 JSON 序列化的普通字典，供统一响应回写。"""
        return {
            "id": format_id(self.id),
            "name": self.name,
            "role_key": self.role_key,
            "data_scope": self.data_scope,
            "sort_order": self.sort_order,
            "status": self.status,
            "remark": self.remark,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
