"""
剧本模块生成会话业务层：会话 CRUD、消息回放与在途生成注册。

- 属主判定经项目收敛：会话本身不落 user_id，访问权 = 所属项目归属当前用户，
  他人项目下的会话一律按"不存在"处理（不泄露存在性）；
- 会话/消息（story_sessions/story_messages）是展示与回放的事实源；
- 在途生成注册表（{session_id_hex: asyncio.Task}）与取消语义对齐
  service/rag/chat.py：stop 即 cancel（推理侧即刻中止），半截内容由
  生成协程的取消分支落库 stopped，收尾帧仍正常下发；
- 删除会话即丢弃未沉淀结果：同事务物理删除消息与会话行，正式资产
  （剧本版本/角色库/立绘）不受影响。
"""

import asyncio
import uuid

from uuid_utils.compat import uuid7

from agent.constants.enums.story import StorySessionType
from database.postgre_client import get_session
from database.story.project import ProjectRepository
from database.story.session import (
    GenerationTaskRepository,
    MessageRepository,
    SessionRepository,
)
from exception.bad_except import bad_except
from service.story.storage import SESSION_ASSET_ROOT, rmdir_if_empty, unlink_quietly
from utils.logger import logger
from utils.page import build_page_result
from utils.user_context import UserContext

# 在途生成任务注册表（强引用 + done 回调条件清除；key 为 session_id hex）。
# 值为 None 表示"已占位未注册"的互斥 sentinel：占位到注册真实任务之间存在
# await 窗口（DB 属主校验/落库），先原子占位防止并发请求同时穿透互斥检查。
_generation_tasks: dict[str, asyncio.Task | None] = {}


def _unregister(session_id_hex: str, done_task: asyncio.Task) -> None:
    """条件注销：仅当注册表当前条目就是本任务时才清除（防误删后注册的新条目）。"""
    if _generation_tasks.get(session_id_hex) is done_task:
        _generation_tasks.pop(session_id_hex, None)


def reserve_session(session_id_hex: str) -> None:
    """会话级生成互斥原子占位：已占用（sentinel 或在途任务）则拒绝。"""
    existing = _generation_tasks.get(session_id_hex)
    if existing is None or existing.done():
        _generation_tasks[session_id_hex] = None
    else:
        bad_except("上一条生成尚未完成，请稍候或先停止生成")


def release_session(session_id_hex: str) -> None:
    """归还互斥占位（仅在条目仍为 sentinel 时清除，不影响真实任务）。"""
    if _generation_tasks.get(session_id_hex) is None:
        _generation_tasks.pop(session_id_hex, None)


def register_generation(session_id_hex: str, task: asyncio.Task) -> None:
    """注册会话在途生成任务（done 后条件清除），替换占位 sentinel。"""
    _generation_tasks[session_id_hex] = task
    task.add_done_callback(
        lambda done_task: _unregister(session_id_hex, done_task)
    )


def cancel_generation(session_id_hex: str) -> bool:
    """取消会话在途生成任务（幂等）：有在途任务返回 True，否则 False。"""
    task = _generation_tasks.get(session_id_hex)
    if task is None or task.done():
        return False
    task.cancel()
    return True


def assert_session_free(session_id_hex: str) -> None:
    """同会话生成互斥：在途任务或占位 sentinel 未结束时拒绝新请求。"""
    existing = _generation_tasks.get(session_id_hex)
    if existing is None:
        return
    if isinstance(existing, asyncio.Task) and existing.done():
        return
    bad_except("上一条生成尚未完成，请稍候或先停止生成")


async def reset_stale_generating_messages() -> int:
    """启动清扫：残留 generating 的 story 消息与残留在途状态的生成任务
    统一置为 failed，返回处理条数。

    进程崩溃后内存注册表已清空，占位消息与任务行都不会自然到达终态；
    任务行若不清扫，项目级互斥（has_running）会永久拒绝后续生成。
    """
    async with get_session() as session:
        message_count = await MessageRepository(session).reset_stale_generating()
        task_count = await GenerationTaskRepository(session).reset_stale_running()
        await session.commit()
    total = message_count + task_count
    if total:
        logger.warning(
            f"[STORY] 启动清扫：{message_count} 条残留 generating 消息、"
            f"{task_count} 个残留在途任务已置为 failed"
        )
    return total


def _assert_user_channel(ctx: UserContext) -> None:
    """生成会话仅支持用户通道调用（机器通道无属主概念）。"""
    if not ctx.user_id:
        bad_except("生成会话仅支持用户通道调用")


class StorySessionService:
    """生成会话业务层：项目收敛的属主校验 + 会话/消息管理 + 计数同步。"""

    async def _assert_project_owned(self, session, project_id: uuid.UUID, ctx):
        """项目须存在、未删除且归属当前用户（属主判定收口）。"""
        project = await ProjectRepository(session).get(project_id)
        if (
            project is None
            or project.status == "deleted"
            or project.user_id != ctx.user_id
        ):
            bad_except("项目不存在")
        return project

    async def _assert_session_owned(self, session, session_id: uuid.UUID, ctx):
        """会话须存在且所属项目归属当前用户，返回 (会话, 项目)。"""
        _assert_user_channel(ctx)
        row = await SessionRepository(session).get(session_id)
        if row is None:
            bad_except(f"会话不存在: {session_id.hex}")
        project = await ProjectRepository(session).get(row.project_id)
        if project is None or project.status == "deleted" or project.user_id != ctx.user_id:
            bad_except(f"会话不存在: {session_id.hex}")
        return row, project

    async def _sync_session_count(self, session, project_id: uuid.UUID) -> None:
        """按会话表真实数量重算项目 session_count 冗余计数（事务内重算口径）。"""
        project = await ProjectRepository(session).get(project_id)
        if project is not None:
            count = await SessionRepository(session).count_by_project(project_id)
            project.session_count = count
            await session.flush()

    async def list(self, ctx: UserContext, project_id: uuid.UUID, page: int, size: int):
        """分页列出项目下会话，最近活跃倒序。"""
        _assert_user_channel(ctx)
        async with get_session() as session:
            await self._assert_project_owned(session, project_id, ctx)
            rows, total = await SessionRepository(session).list_by_project(
                project_id, page, size
            )
            return build_page_result([row.to_dict() for row in rows], total, page, size)

    async def create(self, ctx: UserContext, project_id: uuid.UUID, payload) -> dict:
        """创建会话（归属项目属主，标题/类型可选）。"""
        _assert_user_channel(ctx)
        session_type = payload.type or StorySessionType.GENERAL.value
        if session_type not in {item.value for item in StorySessionType}:
            bad_except(f"会话类型非法: {session_type}")
        title = (payload.title or "").strip() or None
        async with get_session() as session:
            await self._assert_project_owned(session, project_id, ctx)
            row = await SessionRepository(session).create(
                session_id=uuid7(),
                project_id=project_id,
                title=title,
                type=session_type,
            )
            await self._sync_session_count(session, project_id)
            await session.commit()
            return row.to_dict()

    async def detail(self, ctx: UserContext, session_id: uuid.UUID) -> dict:
        """会话详情（仅属主可见）。"""
        async with get_session() as session:
            row, _ = await self._assert_session_owned(session, session_id, ctx)
            return row.to_dict()

    async def latest(self, ctx: UserContext, project_id: uuid.UUID) -> dict | None:
        """项目最近活跃会话（抽屉默认打开目标；无会话返回 None）。"""
        _assert_user_channel(ctx)
        async with get_session() as session:
            await self._assert_project_owned(session, project_id, ctx)
            row = await SessionRepository(session).latest_by_project(project_id)
            return row.to_dict() if row is not None else None

    async def messages(self, ctx: UserContext, session_id: uuid.UUID, page: int, size: int):
        """会话消息历史（仅属主可见），按 sequence 升序分页。"""
        async with get_session() as session:
            await self._assert_session_owned(session, session_id, ctx)
            rows, total = await MessageRepository(session).list_by_session(
                session_id, page, size
            )
            return build_page_result([row.to_dict() for row in rows], total, page, size)

    async def delete(self, ctx: UserContext, session_id: uuid.UUID) -> None:
        """删除会话：先取消在途任务，同事务物理删除消息与会话行，
        commit 后清理会话产物文件（未沉淀结果随之丢弃不留痕）。"""
        cancel_generation(session_id.hex)
        asset_files: "list[str]" = []
        async with get_session() as session:
            row, project = await self._assert_session_owned(session, session_id, ctx)
            asset_files = await MessageRepository(session).list_image_files(session_id)
            await MessageRepository(session).delete_by_session(session_id)
            await SessionRepository(session).delete(session_id)
            await self._sync_session_count(session, project.id)
            await session.commit()
        # commit 成功后清理会话立绘文件（尽力而为，不阻断删除结果）
        for image_file in asset_files:
            unlink_quietly(image_file)
        rmdir_if_empty(f"{SESSION_ASSET_ROOT}/{session_id.hex}")
