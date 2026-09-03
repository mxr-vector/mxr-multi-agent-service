"""
剧本模块生成会话域 ORM 模型（映射 story schema 会话/消息/生成任务表）。

承载 AI 生成过程：会话与消息是"沉淀前的预览区"（未沉淀结果随会话删除丢弃），
生成任务统一追踪 script/character_art 等异步任务的状态与进度。
"""

import uuid
from datetime import datetime

from sqlalchemy import Integer, SmallInteger, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class StorySession(Base):
    """
    生成会话 ORM 模型（映射 story.story_sessions）。

    一次创作过程的生成历史容器：AI 生成结果默认全部保留在会话内，
    用户选择"沉淀"后才落正式资产；删除会话（连同消息）即丢弃未沉淀结果。
    """

    __tablename__ = "story_sessions"
    __table_args__ = {"schema": "story"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'general'")
    )
    message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_message_at: Mapped[datetime | None] = mapped_column(nullable=True)

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
            "project_id": format_id(self.project_id),
            "title": self.title,
            "type": self.type,
            "message_count": self.message_count,
            "last_message_at": format_datetime(self.last_message_at),
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }


class StoryMessage(Base):
    """
    会话消息 ORM 模型（映射 story.story_messages）。

    不可变追加 + assistant 占位终态更新模型；kind 区分产物类型
    （script/character/art），assistant 产物消息可携带生成结果全文、
    生成图片与结构化数据（params）。
    """

    __tablename__ = "story_messages"
    __table_args__ = {"schema": "story"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'general'")
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    image_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
            "kind": self.kind,
            "content": self.content,
            "image_file": self.image_file,
            "prompt": self.prompt,
            "params": self.params,
            "sequence": self.sequence,
            "status": self.status,
            "error": self.error,
            "created_at": format_datetime(self.created_at),
        }


class StoryGenerationTask(Base):
    """
    AI 生成任务 ORM 模型（映射 story.story_generation_tasks）。

    将"AI 生成过程"从消息中独立出来统一追踪；status 流转
    pending -> queued -> generating -> succeeded/failed/cancelled，
    由业务层校验，与项目其它 schema 一致不落 CHECK 约束。
    """

    __tablename__ = "story_generation_tasks"
    __table_args__ = {"schema": "story"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pending'")
    )
    progress: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_image_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    def to_dict(self, with_result_text: bool = False) -> dict:
        """转为可 JSON 序列化的普通字典。

        result_text 默认不携带（可能为完整剧本长文本，列表场景冗余），
        任务详情按需传 with_result_text=True。
        """
        data = {
            "id": format_id(self.id),
            "project_id": format_id(self.project_id),
            "session_id": format_id(self.session_id),
            "task_type": self.task_type,
            "target_type": self.target_type,
            "target_id": format_id(self.target_id),
            "provider": self.provider,
            "model": self.model,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "params": self.params,
            "status": self.status,
            "progress": self.progress,
            "result_image_file": self.result_image_file,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "started_at": format_datetime(self.started_at),
            "finished_at": format_datetime(self.finished_at),
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
        if with_result_text:
            data["result_text"] = self.result_text
        return data
