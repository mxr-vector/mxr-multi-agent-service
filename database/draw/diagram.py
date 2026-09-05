"""
绘图模块持久层（DAO）。

只负责纯粹的数据访问：写操作只 flush 不 commit，事务原子性由 service 层
在同一个 `async with get_session()` 中聚合多个 repo 操作后统一 commit 保证
（对齐 database/rag/chat.py 的 Repository 约定）。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent.constants.enums.chat import ChatMessageStatus, SessionStatus
from entity.draw.diagram import DrawDiagramVersion, DrawMessage, DrawSession
from utils.page import paginate


class DrawSessionRepository:
    """绘图会话持久层：创建（应用端传入 uuid7 id）、按属主分页列表、冗余字段维护。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        session_id: uuid.UUID,
        user_id: str,
        title: str = "新绘图",
    ) -> DrawSession:
        """插入会话；id 由应用端生成。"""
        draw_session = DrawSession(id=session_id, user_id=user_id, title=title)
        self.session.add(draw_session)
        await self.session.flush()
        return draw_session

    async def list(
        self,
        user_id: str,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[DrawSession], int]:
        """按属主分页列出未删除会话，按最后消息时间倒序（无消息的按创建时间）。"""
        stmt = (
            select(DrawSession)
            .where(
                DrawSession.user_id == user_id,
                DrawSession.status != SessionStatus.DELETED,
            )
            .order_by(
                func.coalesce(
                    DrawSession.last_message_at, DrawSession.created_at
                ).desc()
            )
        )
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def get(self, session_id: uuid.UUID) -> DrawSession | None:
        """按 id 获取会话（含软删行，由业务层决定语义）。"""
        return await self.session.get(DrawSession, session_id)

    async def touch(
        self,
        draw_session: DrawSession,
        message_delta: int = 0,
        last_message_at: datetime | None = None,
    ) -> DrawSession:
        """增量维护冗余字段：消息计数与最后消息时间，并刷新 updated_at。"""
        draw_session.message_count = max(0, draw_session.message_count + message_delta)
        if last_message_at is not None:
            draw_session.last_message_at = last_message_at
        draw_session.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return draw_session

    async def delete(self, draw_session: DrawSession) -> None:
        """物理删除会话行（消息与版本由同事务内其他 repo 清理）。"""
        await self.session.delete(draw_session)
        await self.session.flush()


class DrawMessageRepository:
    """绘图消息持久层：append 写入 + assistant 占位终态更新，sequence 会话内单调分配。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_sequence(self, session_id: uuid.UUID) -> int:
        """取会话内下一个消息序号（当前最大值 + 1，从 1 开始）。"""
        current = await self.session.scalar(
            select(func.max(DrawMessage.sequence)).where(
                DrawMessage.session_id == session_id
            )
        )
        return (current or 0) + 1

    async def append(
        self,
        session_id: uuid.UUID,
        role: str,
        sequence: int,
        content: str = "",
        image_file: str | None = None,
        status: str = "done",
    ) -> DrawMessage:
        """追加一条消息（user 消息可带上传图片引用；assistant 占位传 status='generating'）。"""
        message = DrawMessage(
            session_id=session_id,
            role=role,
            content=content,
            image_file=image_file,
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
    ) -> tuple[list[DrawMessage], int]:
        """按会话分页列出消息，按 sequence 升序。"""
        stmt = (
            select(DrawMessage)
            .where(DrawMessage.session_id == session_id)
            .order_by(DrawMessage.sequence.asc())
        )
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def update_completion(
        self,
        message_id: uuid.UUID,
        status: str,
        content: str | None = None,
        error: str | None = None,
    ) -> DrawMessage | None:
        """更新 assistant 占位行终态（done/stopped/failed），仅覆盖显式传入的字段。"""
        message = await self.session.get(DrawMessage, message_id)
        if message is None:
            return None
        message.status = status
        if content is not None:
            message.content = content
        if error is not None:
            message.error = error
        await self.session.flush()
        return message

    async def reset_stale_generating(self) -> int:
        """启动清扫：把残留的 generating 消息统一置为 failed，返回影响行数。"""
        stmt = (
            update(DrawMessage)
            .where(DrawMessage.status == ChatMessageStatus.GENERATING)
            .values(status=ChatMessageStatus.FAILED, error="服务重启，生成任务中断")
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def delete_by_session(self, session_id: uuid.UUID) -> int:
        """物理删除会话下全部消息（会话删除时同步清理），返回影响行数。"""
        stmt = delete(DrawMessage).where(DrawMessage.session_id == session_id)
        result = await self.session.execute(stmt)
        return result.rowcount or 0


class DrawDiagramVersionRepository:
    """图表版本持久层：append-only 插入，按会话/版本链查询；不提供更新与单删。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        session_id: uuid.UUID,
        source_type: str,
        message_id: uuid.UUID | None = None,
        parent_id: uuid.UUID | None = None,
        mermaid_source: str | None = None,
        drawio_xml: str | None = None,
        preview_file: str | None = None,
    ) -> DrawDiagramVersion:
        """插入一条新版本记录（版本链 append-only，永不覆盖既有行）。"""
        version = DrawDiagramVersion(
            session_id=session_id,
            message_id=message_id,
            parent_id=parent_id,
            source_type=source_type,
            mermaid_source=mermaid_source,
            drawio_xml=drawio_xml,
            preview_file=preview_file,
        )
        self.session.add(version)
        await self.session.flush()
        return version

    async def get(self, version_id: uuid.UUID) -> DrawDiagramVersion | None:
        """按 id 获取版本。"""
        return await self.session.get(DrawDiagramVersion, version_id)

    async def list_by_session(
        self, session_id: uuid.UUID
    ) -> "list[DrawDiagramVersion]":
        """按会话列出全部版本（创建时间升序，uuid7 主键与时间同序）。

        注：返回注解用字符串形式，避免与其他方法名潜在遮蔽问题（对齐既有约定）。
        """
        stmt = (
            select(DrawDiagramVersion)
            .where(DrawDiagramVersion.session_id == session_id)
            .order_by(DrawDiagramVersion.created_at.asc(), DrawDiagramVersion.id.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_session(self, session_id: uuid.UUID) -> int:
        """物理删除会话下全部版本（会话删除时同步清理），返回影响行数。"""
        stmt = delete(DrawDiagramVersion).where(
            DrawDiagramVersion.session_id == session_id
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0
