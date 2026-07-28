import uuid
from datetime import datetime

from sqlalchemy import Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class Folder(Base):
    """
    文件夹树 ORM 模型（映射 rag_folders）。

    - id 由 PostgreSQL 18 的 uuidv7() 服务端默认生成（时间有序）；
    - dept_id 为归属组织/部门（逻辑指向 sys_dept.id，空字符串表示未归属），由业务层注入，建库后不可变；
    - knowledge_base_id 为所属知识库，创建后不可变，文件夹不跨知识库移动；
    - parent_id 同一知识库内自引用，NULL 表示根文件夹，不加外键/relationship，
      存在性与同库约束由业务层保证；
    - updated_at 由业务层在更新时显式赋值，不依赖数据库触发器。
    """

    __tablename__ = "rag_folders"
    __table_args__ = {"schema": "rag"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    dept_id: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("''")
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
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
            "dept_id": self.dept_id,
            "knowledge_base_id": format_id(self.knowledge_base_id),
            "parent_id": format_id(self.parent_id),
            "name": self.name,
            "sort_order": self.sort_order,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
