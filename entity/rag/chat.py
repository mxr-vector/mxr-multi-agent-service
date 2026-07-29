import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class ChatSession(Base):
    """
    AI 问答会话 ORM 模型（映射 rag.chat_sessions）。

    - id 由应用端（uuid_utils.compat.uuid7）生成并显式传入，同时作为 LangGraph
      checkpointer 的 thread_id；server_default=text("uuidv7()") 仅作兜底；
    - user_id 为属主（用户 32 位 hex 标识），会话仅本人可见（查询一律按 user_id 等值收敛）；
    - title 首轮问答后由 rewrite_model 生成一句摘要（失败回落首问截断）；
    - message_count / last_message_at 为冗余字段，业务层写入消息时同步更新；
    - status 取值 'active'/'deleted'，删除采用软删除。
    """

    __tablename__ = "chat_sessions"
    __table_args__ = {"schema": "rag"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'新对话'")
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


class ChatMessage(Base):
    """
    AI 问答消息 ORM 模型（映射 rag.chat_messages）。

    - 展示级消息快照，与 checkpointer 的图状态快照双轨分离；
    - kb_ids 为消息级检索范围快照（存在 user 消息上，仅溯源）；
    - metrics 为推理复杂度快照（仅 assistant 消息：检索轮数/候选量/
      token 用量/耗时/模型；user 消息为 NULL）；
    - sequence 为会话内单调序号（UNIQUE(session_id, sequence) 保障顺序可靠）；
    - status 生命周期：generating（占位）→ done / stopped / failed，
      服务重启时残留 generating 统一清扫为 failed。
    """

    __tablename__ = "chat_messages"
    __table_args__ = {"schema": "rag"}

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
    thinking: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    kb_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
            "thinking": self.thinking,
            "sources": self.sources,
            "kb_ids": self.kb_ids,
            "metrics": self.metrics,
            "sequence": self.sequence,
            "status": self.status,
            "error": self.error,
            "created_at": format_datetime(self.created_at),
        }
