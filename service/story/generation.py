"""
剧本生成业务层：SSE 流式剧本生成编排（story-ai-workspace）。

对齐 service/rag/chat.py 的编排范式：
- 写库时序（崩溃可恢复）：生成任务（pending）→ user 消息（制作参数快照）→
  assistant 占位（generating）→ 流结束更新终态（done/stopped/failed）；
- 帧协议复用 chat 的 SseEvent（think/answer/done/error），剧本文本走 answer 帧，
  结构化角色卡随 done 帧 meta 一次下发（D2，卡片无需逐 token 流式）；
- 互斥双保险：会话级（内存注册表）+ 项目级（story_generation_tasks 在途检查）；
- 双轨契约（D4）：模型全文经 split_dual_track 剥离角色卡；成功路径落库
  剧本消息 + 每角色一条角色卡消息，并把制作参数回写项目（参数记忆）；
- 历史上下文按 token 预算从最旧裁剪（对齐 chat_graph 的预算口径）。
"""

import asyncio
import time
import uuid
from datetime import datetime, timezone

from uuid_utils.compat import uuid7

from agent.constants.enums.chat import (
    ChatMessageStatus,
    ChatRole,
    SseEvent,
)
from agent.constants.enums.story import StoryMessageKind, StoryTaskStatus, StoryTaskType
from agent.prompts.story import CARD_DATA_KEY, HISTORY_EMPTY, SCRIPT_SYSTEM_PROMPT
from agent.skills.loader import get_style, load_skill_excerpt
from core.config_snapshot import CFG
from database.postgre_client import get_session
from database.story.project import ProjectRepository
from database.story.session import (
    GenerationTaskRepository,
    MessageRepository,
    SessionRepository,
)
from exception.bad_except import bad_except
from model.chat.factory import build_chat_model
from service.story.contract import split_dual_track
from service.story.session import (
    StorySessionService,
    register_generation,
    release_session,
    reserve_session,
)
from utils.logger import logger
from utils.page import build_page_result
from utils.stream_runtime import sse_frame, spawn_side_task
from utils.token_count import count_tokens

# 输入预算安全边际（覆盖估算偏差，对齐 chat_graph）
_INPUT_BUDGET_SAFETY_MARGIN = 0.10
# 历史拼装最多取最近 N 条消息
_HISTORY_MAX_MESSAGES = 8
# 历史单条内容截断（角色卡/剧本全文入历史时防止单条独占预算）
_HISTORY_ITEM_MAX_CHARS = 4000
# 历史文本行级固定开销（行分隔/角色标记）
_LINE_FIXED_TOKENS = 2


def _trim_history_lines(lines: list[str], budget: int, model_name: str) -> str:
    """历史行按预算从最旧丢弃（对齐 chat_graph._trim_text_lines_to_budget）。"""
    if budget <= 0 or not lines:
        return ""
    acc = 0
    kept: list[str] = []
    for line in reversed(lines):
        cost = count_tokens(model_name, line) + _LINE_FIXED_TOKENS
        if acc + cost > budget:
            break
        acc += cost
        kept.append(line)
    if len(kept) < len(lines):
        logger.debug(f"[STORY] 历史预算裁剪：{len(lines)} → {len(kept)} 行")
    return "\n".join(reversed(kept))


class StoryGenerationService:
    """剧本生成业务层：互斥校验、写库时序、模型流式与双轨落库。"""

    def __init__(self) -> None:
        self._session_service = StorySessionService()

    async def stream(
        self,
        ctx,
        session_id: uuid.UUID,
        idea: str,
        style_key: str,
        aspect_ratio: str | None = None,
        episodes: int | None = None,
        tone: str | None = None,
    ):
        """发起一轮流式剧本生成，返回 SSE 帧异步生成器。

        进入流之前完成：风格解析（未注册拒绝）、会话属主校验、会话级与
        项目级互斥、生成任务落库、user 消息 + assistant 占位落库。
        """
        if not ctx.user_id:
            bad_except("剧本生成仅支持用户通道调用")
        idea = (idea or "").strip()
        if not idea:
            bad_except("创作需求不能为空")
        style = get_style(style_key)
        if aspect_ratio and aspect_ratio not in style.aspect_ratios:
            bad_except(
                f"画幅 {aspect_ratio} 不属于风格 {style.key}"
                f"（可选：{'/'.join(style.aspect_ratios)}）"
            )
        params_snapshot = {
            "style_key": style.key,
            "style_name": style.name,
            "aspect_ratio": aspect_ratio or style.aspect_ratios[0],
            "episodes": episodes,
            "tone": tone,
        }
        session_hex = session_id.hex
        # 会话级互斥（内存注册表）：先原子占位，防"校验→注册"间 await 窗口
        # 被并发请求穿透（TOCTOU）；后续任一步失败都须归还占位
        reserve_session(session_hex)
        try:
            async with get_session() as session:
                story_session, project = await self._session_service._assert_session_owned(
                    session, session_id, ctx
                )
                task_repo = GenerationTaskRepository(session)
                # 项目级互斥（任务表在途检查，覆盖多会话并发场景）
                if await task_repo.has_running(project.id):
                    bad_except("本项目已有生成任务进行中，请稍候或先停止")
                message_repo = MessageRepository(session)
                # 历史在追加本轮消息前取（不含本轮）
                recent = await message_repo.list_recent(session_id, _HISTORY_MAX_MESSAGES)
                history_lines = [
                    f"{row.role}: {(row.content or '')[:_HISTORY_ITEM_MAX_CHARS]}"
                    for row in recent
                    if row.content
                ]
                now = datetime.now(timezone.utc)
                gen_task = await task_repo.create(
                    task_id=uuid7(),
                    project_id=project.id,
                    task_type=StoryTaskType.SCRIPT.value,
                    session_id=session_id,
                    prompt=idea,
                    params=params_snapshot,
                    provider="chat",
                    model=CFG.chat.model_name,
                )
                user_seq = await message_repo.next_sequence(session_id)
                await message_repo.create(
                    message_id=uuid7(),
                    session_id=session_id,
                    role=ChatRole.USER.value,
                    sequence=user_seq,
                    content=idea,
                    params=params_snapshot,
                )
                assistant_message = await message_repo.create(
                    message_id=uuid7(),
                    session_id=session_id,
                    role=ChatRole.ASSISTANT.value,
                    sequence=user_seq + 1,
                    kind=StoryMessageKind.SCRIPT.value,
                    status=ChatMessageStatus.GENERATING.value,
                )
                await SessionRepository(session).touch(
                    story_session, message_delta=2, message_at=now
                )
                await session.commit()

            queue: asyncio.Queue[str | None] = asyncio.Queue()
            task = asyncio.create_task(
                self._generate(
                    queue=queue,
                    session_id=session_id,
                    project_id=project.id,
                    assistant_message_id=assistant_message.id,
                    gen_task_id=gen_task.id,
                    idea=idea,
                    style=style,
                    params_snapshot=params_snapshot,
                    history_lines=history_lines,
                )
            )
            register_generation(session_hex, task)
        except BaseException:
            release_session(session_hex)
            raise

        async def _frames():
            try:
                while True:
                    frame = await queue.get()
                    if frame is None:
                        break
                    yield frame
            finally:
                # 客户端断连时同步取消生成，避免孤儿推理（半截内容落库 stopped）
                if not task.done():
                    task.cancel()

        return _frames()

    async def _generate(
        self,
        queue: asyncio.Queue,
        session_id: uuid.UUID,
        project_id: uuid.UUID,
        assistant_message_id: uuid.UUID,
        gen_task_id: uuid.UUID,
        idea: str,
        style,
        params_snapshot: dict,
        history_lines: list[str],
    ) -> None:
        """生成协程：模型流式 → answer 帧；终态落库并发收尾帧。"""
        session_hex = session_id.hex
        event_id = 0
        answer_parts: list[str] = []
        started_at = time.monotonic()
        model_name = CFG.chat.model_name

        def _put(event: SseEvent, data) -> None:
            nonlocal event_id
            event_id += 1
            queue.put_nowait(sse_frame(event_id, event, data))

        async def _update_task(fields: dict) -> None:
            async with get_session() as db:
                row = await GenerationTaskRepository(db).get(gen_task_id)
                if row is not None:
                    await GenerationTaskRepository(db).update_fields(row, fields)
                    await db.commit()

        try:
            await _update_task(
                {
                    "status": StoryTaskStatus.GENERATING.value,
                    "started_at": datetime.now(timezone.utc),
                }
            )
            # 系统提示装配：技能节选 + 参数 + 历史（按输入预算裁剪）
            excerpt = load_skill_excerpt(style.skill_dir, style.section_keywords)
            params_hint = "\n".join(
                f"- {key}: {value}" for key, value in params_snapshot.items() if value
            )
            context_window = CFG.chat.context_window
            budget = (
                context_window
                - CFG.chat_max_output_tokens
                - int(context_window * _INPUT_BUDGET_SAFETY_MARGIN)
            )
            fixed_cost = count_tokens(
                model_name,
                SCRIPT_SYSTEM_PROMPT.format(
                    style_name=style.name,
                    skill_excerpt=excerpt,
                    params_hint=params_hint,
                    history_block="",
                    idea_block=idea,
                ),
            )
            history_block = _trim_history_lines(
                history_lines, budget - fixed_cost, model_name
            ) or (HISTORY_EMPTY if not history_lines else "")
            system_prompt = SCRIPT_SYSTEM_PROMPT.format(
                style_name=style.name,
                skill_excerpt=excerpt,
                params_hint=params_hint,
                history_block=history_block or HISTORY_EMPTY,
                idea_block=idea,
            )
            _put(SseEvent.THINK, {"text": "正在创作剧本...", "session_id": session_hex})

            model = build_chat_model()
            async for chunk in model.astream(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": idea},
                ]
            ):
                delta = chunk.content if isinstance(chunk.content, str) else ""
                if delta:
                    answer_parts.append(delta)
                    _put(SseEvent.ANSWER, {"delta": delta})

            full_text = "".join(answer_parts)
            duration_ms = round((time.monotonic() - started_at) * 1000)
            # 双轨剥离：剧本文本 + 角色卡（解析失败降级纯剧本，不阻断）
            track = split_dual_track(full_text)
            await self._finalize_success(
                session_id=session_id,
                project_id=project_id,
                assistant_message_id=assistant_message_id,
                gen_task_id=gen_task_id,
                track=track,
                params_snapshot=params_snapshot,
                duration_ms=duration_ms,
            )
            await _update_task(
                {
                    "status": StoryTaskStatus.SUCCEEDED.value,
                    "progress": 100,
                    "result_text": track.script_text,
                    "finished_at": datetime.now(timezone.utc),
                }
            )
            _put(
                SseEvent.DONE,
                {
                    "session_id": session_hex,
                    "message_id": assistant_message_id.hex,
                    "status": ChatMessageStatus.DONE.value,
                    "cards": track.cards,
                    "cards_ok": track.ok,
                    "cards_error": track.error,
                    "params": params_snapshot,
                },
            )
        except asyncio.CancelledError:
            # 用户停止：半截内容落库 stopped（保留可查），收尾帧正常下发
            partial = "".join(answer_parts)
            duration_ms = round((time.monotonic() - started_at) * 1000)
            spawn_side_task(
                self._finalize_terminal(
                    assistant_message_id,
                    session_id,
                    status=ChatMessageStatus.STOPPED.value,
                    content=partial,
                    params={"cards_note": "生成被停止，角色卡未产出"},
                )
            )
            spawn_side_task(
                _update_task(
                    {
                        "status": StoryTaskStatus.CANCELLED.value,
                        "finished_at": datetime.now(timezone.utc),
                        "error_message": "用户停止生成",
                    }
                )
            )
            _put(
                SseEvent.DONE,
                {
                    "session_id": session_hex,
                    "message_id": assistant_message_id.hex,
                    "status": ChatMessageStatus.STOPPED.value,
                    "duration_ms": duration_ms,
                },
            )
            raise
        except Exception as exc:
            logger.exception(f"[STORY] 剧本生成失败 session={session_hex}: {exc}")
            partial = "".join(answer_parts)
            spawn_side_task(
                self._finalize_terminal(
                    assistant_message_id,
                    session_id,
                    status=ChatMessageStatus.FAILED.value,
                    content=partial,
                    error=str(exc),
                )
            )
            spawn_side_task(
                _update_task(
                    {
                        "status": StoryTaskStatus.FAILED.value,
                        "finished_at": datetime.now(timezone.utc),
                        "error_message": str(exc)[:500],
                    }
                )
            )
            _put(SseEvent.ERROR, {"msg": "剧本生成失败，请稍后重试"})
        finally:
            queue.put_nowait(None)

    async def stop(self, ctx, session_id: uuid.UUID) -> bool:
        """停止会话在途生成（幂等）；返回是否实际取消。"""
        if not ctx.user_id:
            bad_except("剧本生成仅支持用户通道调用")
        async with get_session() as db:
            await self._session_service._assert_session_owned(db, session_id, ctx)
        return cancel_generation(session_id.hex)

    async def task_detail(self, ctx, task_id: uuid.UUID, with_result_text: bool = False) -> dict:
        """生成任务详情（属主经项目收敛）。"""
        if not ctx.user_id:
            bad_except("剧本生成仅支持用户通道调用")
        async with get_session() as db:
            task = await GenerationTaskRepository(db).get(task_id)
            if task is None:
                bad_except(f"生成任务不存在: {task_id.hex}")
            project = await ProjectRepository(db).get(task.project_id)
            if (
                project is None
                or project.status == "deleted"
                or project.user_id != ctx.user_id
            ):
                bad_except(f"生成任务不存在: {task_id.hex}")
            return task.to_dict(with_result_text=with_result_text)

    async def list_tasks(
        self,
        ctx,
        project_id: uuid.UUID,
        page: int,
        size: int,
        status: str | None = None,
    ):
        """项目生成任务分页列表（属主经项目收敛，创建时间倒序）。"""
        if not ctx.user_id:
            bad_except("剧本生成仅支持用户通道调用")
        async with get_session() as db:
            await self._session_service._assert_project_owned(db, project_id, ctx)
            rows, total = await GenerationTaskRepository(db).list_by_project(
                project_id, page, size, status
            )
            return build_page_result([row.to_dict() for row in rows], total, page, size)

    async def _finalize_success(
        self,
        session_id: uuid.UUID,
        project_id: uuid.UUID,
        assistant_message_id: uuid.UUID,
        gen_task_id: uuid.UUID,
        track,
        params_snapshot: dict,
        duration_ms: int,
    ) -> None:
        """成功收尾：剧本消息终态 + 角色卡消息落库 + 制作参数回写项目。"""
        async with get_session() as db:
            message_repo = MessageRepository(db)
            message = await message_repo.get(assistant_message_id)
            if message is not None:
                await message_repo.update_fields(
                    message,
                    {
                        "content": track.script_text,
                        "status": ChatMessageStatus.DONE.value,
                        "params": {
                            **params_snapshot,
                            "generation_task_id": gen_task_id.hex,
                            "cards_ok": track.ok,
                            "cards_error": track.error,
                            "duration_ms": duration_ms,
                        },
                    },
                )
            # 角色卡逐条落库（kind='character'，卡片结构化数据挂 params）
            if track.cards:
                story_session = await SessionRepository(db).get(session_id)
                for card in track.cards:
                    seq = await message_repo.next_sequence(session_id)
                    await message_repo.create(
                        message_id=uuid7(),
                        session_id=session_id,
                        role=ChatRole.ASSISTANT.value,
                        sequence=seq,
                        kind=StoryMessageKind.CHARACTER.value,
                        content=f"角色卡：{card['name']}",
                        prompt=card.get("art_prompt"),
                        params={CARD_DATA_KEY: card, **params_snapshot},
                    )
                if story_session is not None:
                    await SessionRepository(db).touch(
                        story_session,
                        message_delta=len(track.cards),
                        message_at=datetime.now(timezone.utc),
                    )
            # 制作参数回写项目（再次生成时作默认值）+ 生成冗余计数同步
            task_repo = GenerationTaskRepository(db)
            project = await ProjectRepository(db).get(project_id)
            if project is not None:
                await ProjectRepository(db).update_fields(
                    project,
                    {
                        "style_key": params_snapshot["style_key"],
                        "production_params": {
                            key: value
                            for key, value in params_snapshot.items()
                            if key not in ("style_key",)
                        },
                        "generation_count": await task_repo.count_by_project(project_id),
                        "last_generated_at": datetime.now(timezone.utc),
                    },
                )
            await db.commit()

    async def _finalize_terminal(
        self,
        assistant_message_id: uuid.UUID,
        session_id: uuid.UUID,
        status: str,
        content: str,
        params: dict | None = None,
        error: str | None = None,
    ) -> None:
        """非成功终态（stopped/failed）：半截内容保留，刷新会话活跃时间。"""
        async with get_session() as db:
            message_repo = MessageRepository(db)
            message = await message_repo.get(assistant_message_id)
            if message is not None:
                await message_repo.update_fields(
                    message,
                    {"content": content, "status": status, "error": error},
                )
            story_session = await SessionRepository(db).get(session_id)
            if story_session is not None:
                await SessionRepository(db).touch(
                    story_session, message_at=datetime.now(timezone.utc)
                )
            await db.commit()
