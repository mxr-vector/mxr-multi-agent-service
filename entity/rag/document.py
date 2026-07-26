import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class Document(Base):
    """
    父文档 ORM 模型（映射 rag_documents）。

    - id 由 PostgreSQL 18 的 uuidv7() 服务端默认生成，可直接与 Qdrant 关联；
    - tenant_id 为多租户隔离标识，由业务层注入（缺省 'default'），建库后不可变；
    - knowledge_base_id 逻辑关联 rag_knowledge_bases.id，不加外键/relationship；
    - content_hash 为 sha256(content)，用于判断源文件是否变更（增量同步）；
    - status 取值 'pending'/'active'/'reindexing'/'deleted'，由业务层校验（无 CHECK）；
    - version 每次重新切块 +1，配合 rag_chunks.document_version 做灰度重建；
    - updated_at 由业务层在 UPDATE 时显式赋值，不依赖数据库触发器。
    """

    __tablename__ = "rag_documents"
    __table_args__ = {"schema": "rag"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'default'")
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )

    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_system: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    doc_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    source_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    valid_from: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    valid_until: Mapped[datetime | None] = mapped_column(nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
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
            "knowledge_base_id": format_id(self.knowledge_base_id),
            "folder_id": format_id(self.folder_id),
            "source_uri": self.source_uri,
            "source_system": self.source_system,
            "title": self.title,
            "doc_type": self.doc_type,
            "content": self.content,
            "content_hash": self.content_hash,
            "metadata": self.doc_metadata,
            "source_updated_at": self.source_updated_at,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "last_verified_at": self.last_verified_at,
            "status": self.status,
            "version": self.version,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
