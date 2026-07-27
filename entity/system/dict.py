import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class DictType(Base):
    """
    字典类型 ORM 模型（映射 sys_dict_type）。

    - id 由 PostgreSQL 18 的 uuidv7() 服务端默认生成（时间有序）；
    - type 为字典类型键（如 'sys_sex'），全局唯一，
      字典数据以该字符串逻辑关联，修改 type 时由业务层同事务级联更新；
    - updated_at 由业务层在更新时显式赋值，不依赖数据库触发器。
    """

    __tablename__ = "sys_dict_type"
    __table_args__ = {"schema": "sys"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
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
            "type": self.type,
            "status": self.status,
            "remark": self.remark,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }


class DictData(Base):
    """
    字典数据 ORM 模型（映射 sys_dict_data）。

    - dict_type 以字符串逻辑关联 sys_dict_type.type（免 join，消费场景为
      前端下拉框按 type 取数），存在性由业务层保证；
    - sort_order 同类型内排序，is_default 标记默认选项；
    - updated_at 由业务层在更新时显式赋值。
    """

    __tablename__ = "sys_dict_data"
    __table_args__ = {"schema": "sys"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    dict_type: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
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
            "dict_type": self.dict_type,
            "label": self.label,
            "value": self.value,
            "sort_order": self.sort_order,
            "is_default": self.is_default,
            "status": self.status,
            "remark": self.remark,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
