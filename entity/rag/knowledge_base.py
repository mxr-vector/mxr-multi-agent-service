import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class KnowledgeBase(Base):
    """
    知识库 ORM 模型（映射 rag_knowledge_bases）。

    - id 主键使用时间有序的 UUIDv7：正常创建路径由应用端（uuid_utils.compat.uuid7）
      生成并显式传入，以便同一事务内由 id 派生 Qdrant collection 名；
      server_default=text("uuidv7()") 保留作为底层兜底（省略 id 的直接插入仍能得到时间有序 id）；
    - dept_id 为归属组织/部门（逻辑指向 sys_dept.id，空字符串表示未归属），由业务层注入，建库后不可变；
    - qdrant_collection / embedding_* 建库后不可变，避免与未来 Qdrant collection 失配；
    - status 取值 'active'/'archived'/'deleted'，删除采用软删除（status='deleted'）；
    - document_count / total_chunk_count 为冗余计数，本轮保持默认。
    """

    __tablename__ = "rag_knowledge_bases"
    __table_args__ = {"schema": "rag"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    dept_id: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("''")
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)

    qdrant_collection: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)

    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'private'")
    )
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True)

    document_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    total_chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

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
            "dept_id": self.dept_id,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "qdrant_collection": self.qdrant_collection,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "embedding_dim": self.embedding_dim,
            "visibility": self.visibility,
            "owner": self.owner,
            "document_count": self.document_count,
            "total_chunk_count": self.total_chunk_count,
            "status": self.status,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
