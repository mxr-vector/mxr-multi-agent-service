import uuid
from datetime import datetime

from sqlalchemy import Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class Dept(Base):
    """
    部门树 ORM 模型（映射 sys_dept）。

    - parent_id 自引用，NULL 表示顶级部门，不加外键/relationship，
      存在性与防环由业务层保证（复刻 rag_folders 模式）；
    - updated_at 由业务层在更新时显式赋值，不依赖数据库触发器。
    """

    __tablename__ = "sys_dept"
    __table_args__ = {"schema": "sys"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    leader: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )

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
            "parent_id": format_id(self.parent_id),
            "name": self.name,
            "sort_order": self.sort_order,
            "leader": self.leader,
            "status": self.status,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
