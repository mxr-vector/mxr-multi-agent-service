"""
绘图模块 ORM 模型（映射 draw schema 三张表）。

- 会话/消息与 rag.chat_* 同构但独立：绘图不接入 RAG 检索链路；
- 图表版本为 append-only 版本链：AI 生成与用户编辑保存均插入新行，
  parent_id 指向基线版本，不做覆盖更新（无冲突提示交互）。
"""

import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class DrawSession(Base):
    """
    绘图会话 ORM 模型（映射 draw.draw_sessions）。

    - id 由应用端（uuid_utils.compat.uuid7）生成并显式传入，server_default 仅兜底；
    - user_id 为属主（32 位无连字符 hex），会话仅本人可见；
    - title 取首问截断；message_count / last_message_at 为冗余字段。
    """

    __tablename__ = "draw_sessions"
    __table_args__ = {"schema": "draw"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'新绘图'")
    )
    message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_message_at: Mapped[datetime | None] = mapped_column(nullable=True)
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
            "user_id": self.user_id,
            "title": self.title,
            "message_count": self.message_count,
            "last_message_at": format_datetime(self.last_message_at),
            "status": self.status,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }


class DrawMessage(Base):
    """
    绘图消息 ORM 模型（映射 draw.draw_messages）。

    - 不可变追加 + assistant 占位终态更新模型（对齐 rag.chat_messages）；
    - image_file 为 user 消息上传图片的存储相对路径（data/ 下），无图为 None；
    - sequence 为会话内单调序号（UNIQUE(session_id, sequence)）；
    - status 生命周期：generating（占位）→ done / stopped / failed。
    """

    __tablename__ = "draw_messages"
    __table_args__ = {"schema": "draw"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    image_file: Mapped[str | None] = mapped_column(String(300), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'done'")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict:
        """转为可 JSON 序列化的普通字典，供统一响应回写。"""
        return {
            "id": format_id(self.id),
            "session_id": format_id(self.session_id),
            "role": self.role,
            "content": self.content,
            "image_file": self.image_file,
            "sequence": self.sequence,
            "status": self.status,
            "error": self.error,
            "created_at": format_datetime(self.created_at),
        }


class DrawDiagramVersion(Base):
    """
    图表版本 ORM 模型（映射 draw.draw_diagram_versions，append-only 版本链）。

    - source_type='ai'：mermaid_source 必有，drawio_xml/preview_file 为 None
      （预览由前端 mermaid.js 实时渲染）；
    - source_type='user'：drawio_xml 与 preview_file（内嵌 XML 的 xmlpng）必有，
      mermaid_source 冗余保存其基线的源；
    - parent_id 指向基线版本（AI 首版为 None），无覆盖更新。
    """

    __tablename__ = "draw_diagram_versions"
    __table_args__ = {"schema": "draw"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    mermaid_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    drawio_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_file: Mapped[str | None] = mapped_column(String(300), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    def to_dict(self, with_xml: bool = False) -> dict:
        """转为可 JSON 序列化的普通字典。

        列表场景 drawio_xml 体积大，默认不外发；详情/编辑加载时传
        with_xml=True 携带完整 XML。
        """
        data = {
            "id": format_id(self.id),
            "session_id": format_id(self.session_id),
            "message_id": format_id(self.message_id),
            "parent_id": format_id(self.parent_id),
            "source_type": self.source_type,
            "mermaid_source": self.mermaid_source,
            "preview_file": self.preview_file,
            "created_at": format_datetime(self.created_at),
        }
        if with_xml:
            data["drawio_xml"] = self.drawio_xml
        return data
