"""Entity bridge index ORM models (rag.entity_index_* tables).

Offline-built inverted index powering query-time entity linking and one-hop
co-occurrence expansion (see openspec change entity-bridge-index).  Generic
entities are decided by corpus document frequency, not vocabularies.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, func, text
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


class EntityIndexRelation(Base):
    """类型化关系 + 桥接事实句（离线 LLM 抽取，来源块指针）。"""

    __tablename__ = "entity_index_relations"
    __table_args__ = {"schema": "rag"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    head_entity: Mapped[str] = mapped_column(String(256), nullable=False)
    tail_entity: Mapped[str] = mapped_column(String(256), nullable=False)
    relation: Mapped[str] = mapped_column(String(256), nullable=False)
    fact_text: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )


class EntityIndexExtractProgress(Base):
    """关系抽取进度：断点续建与幂等（kb, chunk 粒度）。"""

    __tablename__ = "entity_index_extract_progress"
    __table_args__ = {"schema": "rag"}

    kb_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="done")
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
