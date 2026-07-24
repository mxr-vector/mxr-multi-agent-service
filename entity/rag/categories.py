import uuid
from datetime import datetime

from sqlalchemy import Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class Category(Base):
    """
    分类树 ORM 模型（映射 rag_categories）。

    - id 由 PostgreSQL 18 的 uuidv7() 服务端默认生成（时间有序）；
    - tenant_id 为多租户隔离标识，由业务层注入（缺省 'default'），建库后不可变；
    - parent_id 自引用，NULL 表示根分类，不加外键/relationship，存在性由业务层保证；
    - updated_at 由业务层在更新时显式赋值，不依赖数据库触发器。
    """

    __tablename__ = "rag_categories"
    __table_args__ = {"schema": "rag"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'default'")
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
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
            "tenant_id": self.tenant_id,
            "parent_id": format_id(self.parent_id),
            "name": self.name,
            "sort_order": self.sort_order,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
