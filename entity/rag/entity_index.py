"""Entity bridge index ORM models (rag.entity_index_* tables).

Offline-built inverted index powering query-time entity linking and one-hop
co-occurrence expansion (see openspec change entity-bridge-index).  Generic
entities are decided by corpus document frequency, not vocabularies.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base


class EntityIndexEntity(Base):
    """实体统计行：(kb, entity) 唯一，doc_freq 与统计判据 is_generic。"""

    __tablename__ = "entity_index_entities"
    __table_args__ = {"schema": "rag"}

    kb_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    entity: Mapped[str] = mapped_column(String(256), primary_key=True)
    doc_freq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_generic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )


class EntityIndexPosting(Base):
    """倒排项：实体 -> 文档（kb, entity, document_id 唯一）。"""

    __tablename__ = "entity_index_postings"
    __table_args__ = {"schema": "rag"}

    kb_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    entity: Mapped[str] = mapped_column(String(256), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
