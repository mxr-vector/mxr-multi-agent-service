import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base


class KnowledgeBase(Base):
    """
    知识库 ORM 模型（映射 rag_knowledge_bases）。

    - id 由 PostgreSQL 18 的 uuidv7() 服务端默认生成；
    - code 具有 UNIQUE 约束，重复由业务层转为友好失败；
    - category_id 逻辑关联 rag_categories.id，不加外键/relationship；
    - code / qdrant_collection / embedding_* 建库后不可变，避免与未来 Qdrant collection 失配；
    - status 取值 'active'/'archived'/'deleted'，删除采用软删除（status='deleted'）；
    - document_count / total_chunk_count 为冗余计数，本轮保持默认。
    """

    __tablename__ = "rag_knowledge_bases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
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
            "id": str(self.id),
            "name": self.name,
            "code": self.code,
            "description": self.description,
            "category_id": str(self.category_id) if self.category_id else None,
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
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
