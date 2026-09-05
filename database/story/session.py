"""
剧本模块生成会话域持久层（DAO）。

会话/消息/生成任务三张表：消息追加同步维护会话冗余计数与最后消息时间
（touch），任务状态流转由业务层驱动。写操作只 flush 不 commit，事务原子性
由 service 层统一保证（对齐 database/story/project.py 的 Repository 约定）。
"""

import sys
from pathlib import Path

if __name__ == "__main__":
    # 冒烟直跑时 sys.path[0] 为脚本目录，先注入项目根再导入项目模块
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent.constants.enums.chat import ChatMessageStatus
from agent.constants.enums.story import StoryTaskStatus
from entity.story.session import StoryGenerationTask, StoryMessage, StorySession
from utils.page import paginate


class SessionRepository:
    """生成会话持久层：项目维度 CRUD 与消息冗余计数维护。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        session_id: uuid.UUID,
        project_id: uuid.UUID,
        title: str | None = None,
        type: str = "general",
    ) -> StorySession:
        """插入会话；id 由应用端生成。"""
        row = StorySession(
            id=session_id,
            project_id=project_id,
            title=title,
            type=type,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, session_id: uuid.UUID) -> StorySession | None:
        """按 id 获取会话。"""
        return await self.session.get(StorySession, session_id)

    async def list_by_project(
        self, project_id: uuid.UUID, page: int = 1, size: int = 20
    ) -> tuple[list[StorySession], int]:
        """按项目分页列出会话，最近活跃倒序（无消息按创建时间兜底）。"""
        stmt = (
            select(StorySession)
            .where(StorySession.project_id == project_id)
            .order_by(
                StorySession.last_message_at.desc().nulls_last(),
                StorySession.created_at.desc(),
            )
        )
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def latest_by_project(self, project_id: uuid.UUID) -> StorySession | None:
        """项目最近活跃会话（抽屉默认打开目标）。"""
        rows, _ = await self.list_by_project(project_id, page=1, size=1)
        return rows[0] if rows else None

    async def count_by_project(self, project_id: uuid.UUID) -> int:
        """项目会话总数（项目冗余计数 session_count 重算用）。"""
        stmt = (
            select(func.count())
            .select_from(StorySession)
            .where(StorySession.project_id == project_id)
        )
        return await self.session.scalar(stmt) or 0

    async def touch(
        self, row: StorySession, message_delta: int = 0, message_at: datetime | None = None
    ) -> StorySession:
        """写消息后同步冗余计数与最后消息时间，并刷新 updated_at。"""
        if message_delta:
            row.message_count = (row.message_count or 0) + message_delta
        if message_at is not None:
            row.last_message_at = message_at
        row.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return row

    async def update_fields(self, row: StorySession, fields: dict) -> StorySession:
        """按传入字段局部更新并刷新 updated_at。"""
        for key, value in fields.items():
            setattr(row, key, value)
        row.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return row

    async def delete(self, session_id: uuid.UUID) -> None:
        """物理删除会话行（消息由同事务内 delete_by_session 清理）。"""
        stmt = delete(StorySession).where(StorySession.id == session_id)
        await self.session.execute(stmt)
        await self.session.flush()


class MessageRepository:
    """会话消息持久层：会话内序号分配、不可变追加与终态更新。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_sequence(self, session_id: uuid.UUID) -> int:
        """会话内下一个消息序号（当前最大 + 1，从 0 开始）。"""
        current = await self.session.scalar(
            select(func.max(StoryMessage.sequence)).where(
                StoryMessage.session_id == session_id
            )
        )
        return 0 if current is None else current + 1

    async def create(
        self,
        message_id: uuid.UUID,
        session_id: uuid.UUID,
        role: str,
        sequence: int,
        kind: str = "general",
        content: str = "",
        image_file: str | None = None,
        prompt: str | None = None,
        params: dict | None = None,
        status: str = ChatMessageStatus.DONE,
        error: str | None = None,
    ) -> StoryMessage:
        """插入消息；id 与 sequence 由应用端生成/分配。"""
        row = StoryMessage(
            id=message_id,
            session_id=session_id,
            role=role,
            kind=kind,
            content=content,
            image_file=image_file,
            prompt=prompt,
            params=params,
            sequence=sequence,
            status=status,
            error=error,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, message_id: uuid.UUID) -> StoryMessage | None:
        """按 id 获取消息。"""
        return await self.session.get(StoryMessage, message_id)

    async def get_for_update(self, message_id: uuid.UUID) -> StoryMessage | None:
        """按 id 获取消息并加行锁（SELECT FOR UPDATE，沉淀幂等串行化用）。"""
        stmt = (
            select(StoryMessage)
            .where(StoryMessage.id == message_id)
            .with_for_update()
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_session(
        self, session_id: uuid.UUID, page: int = 1, size: int = 50
    ) -> tuple[list[StoryMessage], int]:
        """按会话分页列出消息，序号升序（回放顺序）。"""
        stmt = (
            select(StoryMessage)
            .where(StoryMessage.session_id == session_id)
            .order_by(StoryMessage.sequence.asc())
        )
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def list_recent(self, session_id: uuid.UUID, limit: int) -> list[StoryMessage]:
        """会话最近 N 条消息（序号升序返回），供生成时拼装历史上下文。"""
        stmt = (
            select(StoryMessage)
            .where(StoryMessage.session_id == session_id)
            .order_by(StoryMessage.sequence.desc())
            .limit(limit)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        rows.reverse()
        return rows

    async def update_fields(self, row: StoryMessage, fields: dict) -> StoryMessage:
        """按传入字段局部更新（assistant 占位终态/产物回填用）。"""
        for key, value in fields.items():
            setattr(row, key, value)
        await self.session.flush()
        return row

    async def reset_stale_generating(self) -> int:
        """全库残留 generating 的消息统一置为 failed（启动清扫崩溃恢复路径）。

        只收敛终态，不改内容：半截文本保留可查。返回处理条数。
        """
        stmt = (
            update(StoryMessage)
            .where(StoryMessage.status == ChatMessageStatus.GENERATING)
            .values(status=ChatMessageStatus.FAILED, error="服务重启导致生成中断")
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def delete_by_session(self, session_id: uuid.UUID) -> int:
        """物理删除会话下全部消息（会话删除时调用），返回影响行数。"""
        stmt = delete(StoryMessage).where(StoryMessage.session_id == session_id)
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def list_image_files(self, session_id: uuid.UUID) -> "list[str]":
        """会话内全部非空 image_file 列表（会话删除后产物文件清理用）。"""
        stmt = select(StoryMessage.image_file).where(
            StoryMessage.session_id == session_id,
            StoryMessage.image_file.isnot(None),
        )
        return list((await self.session.execute(stmt)).scalars().all())


class GenerationTaskRepository:
    """生成任务持久层：任务创建、状态流转与项目级在途检查。"""

    # 在途状态集合（互斥检查口径）
    RUNNING_STATUSES = (
        StoryTaskStatus.PENDING,
        StoryTaskStatus.QUEUED,
        StoryTaskStatus.GENERATING,
    )

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        task_id: uuid.UUID,
        project_id: uuid.UUID,
        task_type: str,
        session_id: uuid.UUID | None = None,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
        provider: str | None = None,
        model: str | None = None,
        prompt: str | None = None,
        negative_prompt: str | None = None,
        params: dict | None = None,
        status: str = StoryTaskStatus.PENDING,
    ) -> StoryGenerationTask:
        """插入生成任务；id 由应用端生成。"""
        row = StoryGenerationTask(
            id=task_id,
            project_id=project_id,
            session_id=session_id,
            task_type=task_type,
            target_type=target_type,
            target_id=target_id,
            provider=provider,
            model=model,
            prompt=prompt,
            negative_prompt=negative_prompt,
            params=params,
            status=status,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, task_id: uuid.UUID) -> StoryGenerationTask | None:
        """按 id 获取任务。"""
        return await self.session.get(StoryGenerationTask, task_id)

    async def has_running(self, project_id: uuid.UUID) -> bool:
        """项目是否存在在途任务（项目级生成互斥检查口径）。"""
        stmt = (
            select(StoryGenerationTask.id)
            .where(
                StoryGenerationTask.project_id == project_id,
                StoryGenerationTask.status.in_(self.RUNNING_STATUSES),
            )
            .limit(1)
        )
        return await self.session.scalar(stmt) is not None

    async def reset_stale_running(self) -> int:
        """全库残留在途状态的任务统一置为 failed（启动清扫崩溃恢复路径）。

        进程重启后内存注册表已清空，任务行不可能再自然到达终态；若不清扫，
        项目级互斥（has_running）会把该项目所有后续生成永久拒绝。
        """
        stmt = (
            update(StoryGenerationTask)
            .where(StoryGenerationTask.status.in_(self.RUNNING_STATUSES))
            .values(
                status=StoryTaskStatus.FAILED,
                error_message="服务重启导致生成中断",
                finished_at=datetime.now(timezone.utc),
            )
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def count_by_project(self, project_id: uuid.UUID) -> int:
        """项目任务总数（项目冗余计数 generation_count 重算用）。"""
        stmt = (
            select(func.count())
            .select_from(StoryGenerationTask)
            .where(StoryGenerationTask.project_id == project_id)
        )
        return await self.session.scalar(stmt) or 0

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        page: int = 1,
        size: int = 20,
        status: str | None = None,
    ) -> tuple[list[StoryGenerationTask], int]:
        """按项目分页列出任务（可按状态过滤），创建时间倒序。"""
        stmt = select(StoryGenerationTask).where(
            StoryGenerationTask.project_id == project_id
        )
        if status:
            stmt = stmt.where(StoryGenerationTask.status == status)
        stmt = stmt.order_by(StoryGenerationTask.created_at.desc())
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def update_fields(self, row: StoryGenerationTask, fields: dict) -> StoryGenerationTask:
        """按传入字段局部更新并刷新 updated_at（状态流转统一入口）。"""
        for key, value in fields.items():
            setattr(row, key, value)
        row.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return row

    async def delete(self, task_id: uuid.UUID) -> None:
        """物理删除任务行（冒烟清理用，常态业务不删任务）。"""
        stmt = delete(StoryGenerationTask).where(StoryGenerationTask.id == task_id)
        await self.session.execute(stmt)
        await self.session.flush()


if __name__ == "__main__":
    # 手动冒烟：会话/消息/任务建查改删各一轮（含序号分配、touch 冗余维护、
    # 会话删除级联清消息、项目级在途检查）。不经常态入口调用须先加载配置快照。
    import asyncio

    from uuid_utils.compat import uuid7

    from core.config_snapshot import CFG
    from database.postgre_client import get_session
    from database.story.project import ProjectRepository

    async def _smoke() -> None:
        await CFG.load()
        user_id = uuid7().hex
        project_id = uuid7()
        session_id = uuid7()
        task_id = uuid7()
        async with get_session() as session:
            project_repo = ProjectRepository(session)
            session_repo = SessionRepository(session)
            message_repo = MessageRepository(session)
            task_repo = GenerationTaskRepository(session)

            # 准备属主项目（会话/任务逻辑关联 project_id）
            await project_repo.create(project_id, user_id, "会话冒烟项目")

            # 1) 会话创建 + 消息追加（序号分配 + touch）
            row = await session_repo.create(session_id, project_id, "冒烟会话", "script")
            assert row.message_count == 0 and row.last_message_at is None
            for i in range(2):
                seq = await message_repo.next_sequence(session_id)
                msg = await message_repo.create(
                    uuid7(), session_id, "assistant", seq,
                    kind="script", content=f"剧本片段{i}", status=ChatMessageStatus.DONE,
                )
                await session_repo.touch(row, message_delta=1, message_at=msg.created_at)
            assert row.message_count == 2 and row.last_message_at is not None

            # 2) 回放与最近消息
            items, total = await message_repo.list_by_session(session_id)
            assert total == 2 and [m.sequence for m in items] == [0, 1]
            recent = await message_repo.list_recent(session_id, limit=1)
            assert len(recent) == 1 and recent[0].sequence == 1

            # 3) 消息终态更新
            await message_repo.update_fields(items[1], {"status": "stopped"})

            # 4) 任务创建 -> 状态流转 -> 在途检查 -> 终态
            task = await task_repo.create(
                task_id, project_id, "script", session_id=session_id, prompt="p"
            )
            assert task.status == StoryTaskStatus.PENDING
            assert await task_repo.has_running(project_id) is True
            await task_repo.update_fields(
                task,
                {"status": StoryTaskStatus.GENERATING, "progress": 50, "started_at": datetime.now(timezone.utc)},
            )
            await task_repo.update_fields(
                task,
                {
                    "status": StoryTaskStatus.SUCCEEDED,
                    "progress": 100,
                    "result_text": "全文",
                    "finished_at": datetime.now(timezone.utc),
                },
            )
            assert await task_repo.has_running(project_id) is False
            sessions, s_total = await session_repo.list_by_project(project_id)
            assert s_total == 1 and sessions[0].id == row.id
            assert await session_repo.count_by_project(project_id) == 1
            assert await task_repo.count_by_project(project_id) == 1

            # 5) 会话删除级联清消息 + 清理冒烟数据
            deleted = await message_repo.delete_by_session(session_id)
            assert deleted == 2
            await session_repo.delete(session_id)
            await task_repo.delete(task_id)
            await project_repo.session.delete(
                await project_repo.get(project_id)
            )
            await project_repo.session.flush()
            assert await message_repo.delete_by_session(session_id) == 0

        print("✓ 会话/消息/任务仓储冒烟通过")

    asyncio.run(_smoke())
