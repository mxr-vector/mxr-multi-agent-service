import uuid
from datetime import datetime

from sqlalchemy import Integer, SmallInteger, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base


class Chunk(Base):
    """
    父子块 ORM 模型（映射 rag_chunks）。

    - id 由 PostgreSQL 18 的 uuidv7() 服务端默认生成，level=0 的 id 即 Qdrant point id；
    - document_id / parent_chunk_id 逻辑关联，不加外键/relationship，业务层保证一致性；
    - document_version 冗余存储文档版本，用于重建索引时新旧版本并存/切换；
    - level=0 为叶子子块（入 Qdrant），level>=1 为父块（仅 PG，用于回写上下文）；
    - chunk_index 为同一 (document_id, document_version, level) 内的顺序号。
    """

    __tablename__ = "rag_chunks"
    __table_args__ = {"schema": "rag"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parent_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)

    level: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    chapter_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunk_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict:
        """转为可 JSON 序列化的普通字典，供统一响应回写。"""
        return {
            "id": str(self.id),
            "document_id": str(self.document_id),
            "parent_chunk_id": (
                str(self.parent_chunk_id) if self.parent_chunk_id else None
            ),
            "document_version": self.document_version,
            "level": self.level,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "token_count": self.token_count,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "chapter_title": self.chapter_title,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "content_hash": self.content_hash,
            "metadata": self.chunk_metadata,
            "created_at": self.created_at,
        }
