import uuid
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from entity.rag.chat import ChatMessage, ChatSession
from utils.page import paginate


class ChatSessionRepository:
    """
    问答会话持久层（DAO）。

    只负责纯粹的数据访问：创建（应用端传入 uuid7 id）、按属主分页列表、
    按 id 获取、软删除/清空、消息计数与标题的冗余字段维护、统计。
    属主校验等业务规则由 service 层收口。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        session_id: uuid.UUID,
        user_id: str,
        title: str = "新对话",
    ) -> ChatSession:
        """插入会话；id 由应用端生成（同时作为 checkpointer thread_id）。"""
        chat_session = ChatSession(
            id=session_id,
            user_id=user_id,
            title=title,
        )
        self.session.add(chat_session)
        await self.session.flush()
        return chat_session

    async def list(
        self,
        user_id: str,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[ChatSession], int]:
        """按属主分页列出未删除会话，按最后消息时间倒序（无消息的按创建时间）。"""
        stmt = (
            select(ChatSession)
            .where(
                ChatSession.user_id == user_id,
                ChatSession.status != "deleted",
            )
            .order_by(
                func.coalesce(
                    ChatSession.last_message_at, ChatSession.created_at
                ).desc()
            )
        )
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def get(self, session_id: uuid.UUID) -> ChatSession | None:
        """按 id 获取会话（含软删行，由业务层决定语义）。"""
        return await self.session.get(ChatSession, session_id)

    async def touch(
        self,
        chat_session: ChatSession,
        message_delta: int = 0,
        last_message_at: datetime | None = None,
    ) -> ChatSession:
        """增量维护冗余字段：消息计数与最后消息时间，并刷新 updated_at。"""
        chat_session.message_count = max(0, chat_session.message_count + message_delta)
        if last_message_at is not None:
            chat_session.last_message_at = last_message_at
        chat_session.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return chat_session

    async def update_title(self, session_id: uuid.UUID, title: str) -> None:
        """更新会话标题（首轮问答后由摘要任务回填），并刷新 updated_at。"""
        chat_session = await self.session.get(ChatSession, session_id)
        if chat_session is None:
            return
        chat_session.title = title
        chat_session.updated_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def soft_delete(self, chat_session: ChatSession) -> ChatSession:
        """软删除：置 status='deleted' 并刷新 updated_at。"""
        chat_session.status = "deleted"
        chat_session.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return chat_session

    async def soft_delete_all(self, user_id: str) -> "list[uuid.UUID]":
        """清空本人全部未删除会话，返回被删会话 id 列表（供同步清理 checkpoint）。

        注：返回注解用字符串形式，避免类作用域内被上方 `list` 方法遮蔽。
        """
        stmt = select(ChatSession).where(
            ChatSession.user_id == user_id,
            ChatSession.status != "deleted",
        )
        result = await self.session.execute(stmt)
        sessions = list(result.scalars().all())
        now = datetime.now(timezone.utc)
        for chat_session in sessions:
            chat_session.status = "deleted"
            chat_session.updated_at = now
        await self.session.flush()
        return [chat_session.id for chat_session in sessions]

    async def stats(self, user_id: str) -> dict:
        """统计本人未删除会话总数与消息总数（消息按未删会话聚合）。"""
        session_count = await self.session.scalar(
            select(func.count())
            .select_from(ChatSession)
            .where(
                ChatSession.user_id == user_id,
                ChatSession.status != "deleted",
            )
        )
        message_count = await self.session.scalar(
            select(func.coalesce(func.sum(ChatSession.message_count), 0)).where(
                ChatSession.user_id == user_id,
                ChatSession.status != "deleted",
            )
        )
        return {
            "total_sessions": session_count or 0,
            "total_messages": message_count or 0,
        }

    async def list_expired_ids(self, before: datetime) -> "list[uuid.UUID]":
        """列出最后消息时间早于阈值的会话 id（供 checkpoint TTL 清理圈定 thread）。

        注：返回注解用字符串形式，避免类作用域内被上方 `list` 方法遮蔽。
        """
        stmt = select(ChatSession.id).where(
            ChatSession.last_message_at.is_not(None),
            ChatSession.last_message_at < before,
        )
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]


class ChatMessageRepository:
    """
    问答消息持久层（DAO）。

    消息为不可变追加 + 终态更新模型：append 写入，update_completion 更新
    assistant 占位行的终态；sequence 由 next_sequence 在会话内单调分配。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_sequence(self, session_id: uuid.UUID) -> int:
        """取会话内下一个消息序号（当前最大值 + 1，从 1 开始）。"""
        current = await self.session.scalar(
            select(func.max(ChatMessage.sequence)).where(
                ChatMessage.session_id == session_id
            )
        )
        return (current or 0) + 1

    async def append(
        self,
        session_id: uuid.UUID,
        role: str,
        sequence: int,
        content: str = "",
        kb_ids: list[str] | None = None,
        status: str = "done",
    ) -> ChatMessage:
        """追加一条消息（user 消息带 kb_ids 快照；assistant 占位传 status='generating'）。"""
        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            kb_ids=kb_ids,
            sequence=sequence,
            status=status,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def list(
        self,
        session_id: uuid.UUID,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[ChatMessage], int]:
        """按会话分页列出消息，按 sequence 升序。"""
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence.asc())
        )
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def list_recent(
        self, session_id: uuid.UUID, limit: int
    ) -> "list[ChatMessage]":
        """取会话最近的 limit 条消息（升序返回），供 checkpoint 缺失时回落改写历史。

        注：返回注解用字符串形式，避免类作用域内被上方 `list` 方法遮蔽。
        """
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        messages = list(result.scalars().all())
        messages.reverse()
        return messages

    async def update_completion(
        self,
        message_id: uuid.UUID,
        status: str,
        content: str | None = None,
        thinking: str | None = None,
        sources: Sequence[dict] | None = None,
        metrics: dict | None = None,
        error: str | None = None,
    ) -> ChatMessage | None:
        """更新 assistant 占位行终态（done/stopped/failed），仅覆盖显式传入的字段。"""
        message = await self.session.get(ChatMessage, message_id)
        if message is None:
            return None
        message.status = status
        if content is not None:
            message.content = content
        if thinking is not None:
            message.thinking = thinking
        if sources is not None:
            message.sources = list(sources)
        if metrics is not None:
            message.metrics = metrics
        if error is not None:
            message.error = error
        await self.session.flush()
        return message

    async def reset_stale_generating(self) -> int:
        """启动清扫：把残留的 generating 消息统一置为 failed，返回影响行数。"""
        stmt = (
            update(ChatMessage)
            .where(ChatMessage.status == "generating")
            .values(status="failed", error="服务重启，生成任务中断")
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0
