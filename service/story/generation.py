"""
剧本生成业务层：SSE 流式剧本生成（story-ai-workspace）。

AI 编排（系统提示装配、生成模型装配、技能工具循环、预算守卫、漏读纠正）
收敛在 LangGraph 创作图 agent/graph/story/graph.py（见 design D9）；本层
只做业务收口（对齐 service/rag/chat.py 的消费范式）：
- 写库时序（崩溃可恢复）：生成任务（pending）→ user 消息（制作参数快照）→
  assistant 占位（generating）→ 流结束更新终态（done/stopped/failed）；
- 帧协议复用 chat 的 SseEvent（think/answer/done/error）：图经 stream_mode
  "custom" 外发 think/answer 事件，本层映射 SSE 帧（answer 帧与累积文本
  单点收口）；结构化角色卡随 done 帧 meta 一次下发（D2，卡片无需逐 token 流式）；
- 图终态（answer + skill_audit）经 stream_mode "updates" 回传；审计随任务
  终态并入 params（成功/取消/失败均落，失败路径也含失败前已读文件清单）；
- 互斥双保险：会话级（内存注册表）+ 项目级（story_generation_tasks 在途检查）；
- 双轨契约（D4）：模型全文经 split_dual_track 剥离角色卡；成功路径落库
  剧本消息 + 每角色一条角色卡消息，并把制作参数回写项目（参数记忆）。
- 消息级辅助动作（rewrite/regenerate/continue）：分支截断、原问题复用与
  断点续写前缀均在同一事务内完成，仅清理会话消息不动已沉淀资产。
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
from agent.constants.enums.story import (
    StoryMessageKind,
    StoryProjectStatus,
    StoryTaskStatus,
    StoryTaskType,
)
from agent.prompts.story import CARD_DATA_KEY, KEYFRAME_DATA_KEY
from agent.skills.loader import STYLE_REGISTRY, get_style
from core.config_snapshot import CFG
from database.postgre_client import get_session
from database.story.project import ProjectRepository
from database.story.session import (
    GenerationTaskRepository,
    MessageRepository,
    SessionRepository,
)
from exception.bad_except import bad_except
from service.story.contract import CARDS_BEGIN, CARDS_END, split_dual_track
from service.story.session import (
    StorySessionService,
    register_generation,
    release_session,
    reserve_session,
)
from utils.logger import logger
from utils.page import build_page_result
from utils.stream_runtime import sse_frame, spawn_side_task

# 历史拼装最多取最近 N 条消息
_HISTORY_MAX_MESSAGES = 8
# 历史单条内容截断（角色卡/剧本全文入历史时防止单条独占预算）
_HISTORY_ITEM_MAX_CHARS = 4000

# 消息级辅助动作：新增 / 覆盖式重编辑 / 重新生成 / 断点续写
_GENERATION_ACTIONS = {"new", "rewrite", "regenerate", "continue"}
# 可重新生成/续写的 assistant 消息类型
_REGENERATABLE_KINDS = (StoryMessageKind.SCRIPT.value, StoryMessageKind.GENERAL.value)
# 允许断点续写的终态
_CONTINUABLE_STATUSES = (
    ChatMessageStatus.STOPPED.value,
    ChatMessageStatus.FAILED.value,
)
# 送模型的续写上下文只取正文尾部（全文仍拼回落库），避免撑爆输入预算
_CONTINUATION_CONTEXT_MAX_CHARS = 6000


class StoryGenerationService:
    """剧本生成业务层：互斥校验、写库时序、消费创作图事件与双轨落库。"""

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
        episode_duration: int | None = None,
        mode: str | None = None,
        image_file: str | None = None,
        images: list[str] | None = None,
        action: str = "new",
        target_message_id: uuid.UUID | None = None,
    ):
        """发起一轮流式剧本生成，返回 SSE 帧异步生成器。

        action 语义（消息级辅助操作）：
        - new：追加新一轮（user 消息 + assistant 占位）；
        - rewrite：覆盖指定 user 问题及其后全部会话消息，按新问题重新生成；
        - regenerate：删除指定 assistant 及其后消息，复用前一条 user 的问题
          与制作参数重新生成；
        - continue：复用被停止/失败的 assistant 行，以其已产出内容为前缀续写。
        覆盖/续写仅清理会话消息，不删除磁盘图片与已沉淀资产。

        进入流之前完成：动作与风格校验、会话属主校验、会话级与项目级互斥、
        目标消息校验、生成任务与消息行写库（单事务单 commit）。
        """
        if not ctx.user_id:
            bad_except("剧本生成仅支持用户通道调用")
        action = (action or "new").strip()
        if action not in _GENERATION_ACTIONS:
            bad_except(f"不支持的生成动作: {action}")
        if action != "new" and target_message_id is None:
            bad_except("缺少目标消息 id")

        payload_images = list(images) if images else ([image_file] if image_file else [])

        if action in ("new", "rewrite"):
            idea = (idea or "").strip()
            if not idea:
                bad_except("创作需求不能为空")
            style = get_style(style_key)
            params_snapshot = self._snapshot_from_payload(
                style,
                aspect_ratio,
                episodes,
                tone,
                episode_duration,
                mode,
                payload_images,
            )
        else:
            # regenerate/continue：风格与参数以原 user 消息快照为准，稍后解析
            style = None
            params_snapshot = None

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
                now = datetime.now(timezone.utc)
                continuation_prefix = ""
                target_hex: str | None = None

                if action == "new":
                    recent = await message_repo.list_recent(
                        session_id, _HISTORY_MAX_MESSAGES
                    )
                    history_lines = self._history_lines(recent)
                    user_seq = await message_repo.next_sequence(session_id)
                    await message_repo.create(
                        message_id=uuid7(),
                        session_id=session_id,
                        role=ChatRole.USER.value,
                        sequence=user_seq,
                        content=idea,
                        image_file=params_snapshot["image_file"],
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
                else:
                    target = await message_repo.get_for_update(target_message_id)
                    self._assert_target_message(target, session_id)
                    target_hex = target.id.hex

                    if action == "rewrite":
                        if target.role != ChatRole.USER.value:
                            bad_except("重新编辑仅支持用户问题消息")
                        # art 等其它用户消息没有制作参数快照，不能按剧本重生成
                        if not isinstance((target.params or {}).get("style_key"), str):
                            bad_except("该用户消息不是剧本生成问题，无法重新编辑")
                        deleted = await message_repo.delete_from_sequence(
                            session_id, target.sequence
                        )
                        recent = await message_repo.list_recent(
                            session_id, _HISTORY_MAX_MESSAGES
                        )
                        history_lines = self._history_lines(recent)
                        user_seq = await message_repo.next_sequence(session_id)
                        await message_repo.create(
                            message_id=uuid7(),
                            session_id=session_id,
                            role=ChatRole.USER.value,
                            sequence=user_seq,
                            content=idea,
                            image_file=params_snapshot["image_file"],
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
                            story_session,
                            message_delta=-deleted + 2,
                            message_at=now,
                        )
                    else:
                        if target.role != ChatRole.ASSISTANT.value:
                            bad_except("该操作仅支持 AI 回答消息")
                        if target.kind not in _REGENERATABLE_KINDS:
                            bad_except("该消息类型不支持重新生成或续写")
                        if target.status == ChatMessageStatus.GENERATING.value:
                            bad_except("该回答仍在生成中")
                        if (
                            action == "continue"
                            and target.status not in _CONTINUABLE_STATUSES
                        ):
                            bad_except("仅被停止或失败的生成可断点续写")

                        origin_user = await message_repo.previous_user(
                            session_id, target.sequence
                        )
                        if origin_user is None:
                            bad_except("未找到该回答对应的用户问题")
                        style, params_snapshot, payload_images = (
                            self._snapshot_from_user(
                                origin_user, style_key, payload_images
                            )
                        )
                        history_lines = self._history_lines(
                            await message_repo.list_before(
                                session_id,
                                origin_user.sequence,
                                _HISTORY_MAX_MESSAGES,
                            )
                        )
                        idea = (origin_user.content or idea).strip()

                        if action == "regenerate":
                            deleted = await message_repo.delete_from_sequence(
                                session_id, target.sequence
                            )
                            assistant_message = await message_repo.create(
                                message_id=uuid7(),
                                session_id=session_id,
                                role=ChatRole.ASSISTANT.value,
                                sequence=await message_repo.next_sequence(session_id),
                                kind=StoryMessageKind.SCRIPT.value,
                                status=ChatMessageStatus.GENERATING.value,
                            )
                            await SessionRepository(session).touch(
                                story_session,
                                message_delta=-deleted + 1,
                                message_at=now,
                            )
                        else:
                            deleted = await message_repo.delete_from_sequence(
                                session_id, target.sequence + 1
                            )
                            continuation_prefix = target.content or ""
                            await message_repo.update_fields(
                                target,
                                {
                                    "status": ChatMessageStatus.GENERATING.value,
                                    "error": None,
                                },
                            )
                            assistant_message = target
                            await SessionRepository(session).touch(
                                story_session,
                                message_delta=-deleted,
                                message_at=now,
                            )

                # 对话模型默认优先采用多模态模型角色
                model_name = (
                    CFG.visual.model_name
                    if (hasattr(CFG, "visual") and CFG.visual and CFG.visual.model_name)
                    else CFG.chat.model_name
                )
                gen_task = await task_repo.create(
                    task_id=uuid7(),
                    project_id=project.id,
                    task_type=StoryTaskType.SCRIPT.value,
                    session_id=session_id,
                    prompt=idea,
                    params={
                        **params_snapshot,
                        "action": action,
                        "target_message_id": target_hex,
                    },
                    provider="chat",
                    model=model_name,
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
                    style_key=style.key,
                    params_snapshot=params_snapshot,
                    history_lines=history_lines,
                    images=payload_images,
                    continuation_prefix=continuation_prefix,
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

    # ---------- 参数快照与校验 ----------

    @staticmethod
    def _assert_target_message(target, session_id: uuid.UUID) -> None:
        """目标消息须存在且属于当前会话（防跨会话操作）。"""
        if target is None or target.session_id != session_id:
            bad_except("目标消息不存在")

    @staticmethod
    def _history_lines(rows) -> list[str]:
        """业务表消息行 → 系统提示历史行（单条截断）。"""
        return [
            f"{row.role}: {(row.content or '')[:_HISTORY_ITEM_MAX_CHARS]}"
            for row in rows
            if row.content
        ]

    @staticmethod
    def _snapshot_from_payload(
        style,
        aspect_ratio: str | None,
        episodes: int | None,
        tone: str | None,
        episode_duration: int | None,
        mode: str | None,
        all_images: list[str],
    ) -> dict:
        """按本次请求参数构建制作参数快照（new/rewrite 使用）。"""
        if aspect_ratio and aspect_ratio not in style.aspect_ratios:
            bad_except(
                f"画幅 {aspect_ratio} 不属于风格 {style.key}"
                f"（可选：{'/'.join(style.aspect_ratios)}）"
            )
        if episode_duration and episode_duration not in (15, 30):
            bad_except("视频模型目前仅支持 15s 或 30s 时长（可选：15/30）")
        return {
            "style_key": style.key,
            "style_name": style.name,
            "aspect_ratio": aspect_ratio or style.aspect_ratios[0],
            "episodes": episodes,
            "tone": tone,
            "episode_duration": episode_duration or 30,
            "mode": mode or "story",
            "image_file": all_images[0] if all_images else None,
            "images": all_images,
        }

    @staticmethod
    def _snapshot_from_user(
        origin_user,
        fallback_style_key: str,
        fallback_images: list[str],
    ) -> tuple:
        """从原 user 消息的 params 还原制作参数（regenerate/continue 使用）。

        风格失效（技能注册表已移除）时回退本次请求的 style_key；画幅/时长
        非法时收敛到该风格的合法缺省值。
        """
        params = origin_user.params or {}
        stored_key = params.get("style_key")
        style_key = (
            stored_key
            if isinstance(stored_key, str) and stored_key in STYLE_REGISTRY
            else fallback_style_key
        )
        style = get_style(style_key)
        aspect_ratio = params.get("aspect_ratio")
        if aspect_ratio not in style.aspect_ratios:
            aspect_ratio = style.aspect_ratios[0]
        episode_duration = params.get("episode_duration")
        if episode_duration not in (15, 30):
            episode_duration = 30
        episodes = params.get("episodes")
        if not isinstance(episodes, int):
            episodes = None
        tone = params.get("tone") if isinstance(params.get("tone"), str) else None
        mode = params.get("mode") if isinstance(params.get("mode"), str) else "story"

        raw_images = params.get("images")
        if not isinstance(raw_images, list):
            stored_image = params.get("image_file")
            raw_images = (
                [stored_image]
                if isinstance(stored_image, str) and stored_image
                else list(fallback_images or [])
            )
        all_images = [img for img in raw_images if isinstance(img, str) and img]
        # 主图可能单独存于 image_file（旧消息），补回参考图列表避免丢失
        stored_image = params.get("image_file")
        if isinstance(stored_image, str) and stored_image and stored_image not in all_images:
            all_images.insert(0, stored_image)

        snapshot = {
            "style_key": style.key,
            "style_name": style.name,
            "aspect_ratio": aspect_ratio,
            "episodes": episodes,
            "tone": tone,
            "episode_duration": episode_duration,
            "mode": mode,
            "image_file": all_images[0] if all_images else None,
            "images": all_images,
        }
        return style, snapshot, all_images

    @staticmethod
    def _strip_unclosed_cards(text: str) -> str:
        """剥离尾部未闭合的角色卡块（中断在 JSON 中时不能作为正文/续写上下文）。"""
        text = text or ""
        begin = text.rfind(CARDS_BEGIN)
        if begin >= 0 and text.find(CARDS_END, begin) < 0:
            return text[:begin].rstrip()
        return text

    @classmethod
    def _continuation_context(cls, prefix: str) -> str:
        """送模型的续写上下文：剥离未闭合卡片块并只保留正文尾部。"""
        text = cls._strip_unclosed_cards(prefix).strip()
        if len(text) > _CONTINUATION_CONTEXT_MAX_CHARS:
            text = text[-_CONTINUATION_CONTEXT_MAX_CHARS:]
        return text

    async def _generate(
        self,
        queue: asyncio.Queue,
        session_id: uuid.UUID,
        project_id: uuid.UUID,
        assistant_message_id: uuid.UUID,
        gen_task_id: uuid.UUID,
        idea: str,
        style_key: str,
        params_snapshot: dict,
        history_lines: list[str],
        images: list[str] | None = None,
        continuation_prefix: str = "",
    ) -> None:
        """图执行协程：astream 事件映射为 SSE 帧入队，终态落库并发收尾帧。"""
        # 局部导入：避免 service 层与 agent 图在模块加载期耦合（对齐 chat）
        from agent.graph.story.graph import story_graph

        session_hex = session_id.hex
        event_id = 0
        answer_parts: list[str] = []
        started_at = time.monotonic()
        # 续写前缀的落库版本：剥离未闭合卡片块，避免拼接后污染正文
        continuation_base = self._strip_unclosed_cards(continuation_prefix)
        # 技能调用审计：图经 custom audit 事件增量回传（含失败前已读文件），
        # 随任务终态并入 params（成功/取消/失败均落），日志兜底
        skill_audit = {"tool_rounds": 0, "files_read": [], "skipped_skill_read": False}

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

        async def _update_task_params(fields: dict) -> None:
            """把技能审计并入任务 params 后更新（读改写，单事务）。"""
            async with get_session() as db:
                row = await GenerationTaskRepository(db).get(gen_task_id)
                if row is not None:
                    await GenerationTaskRepository(db).update_fields(
                        row,
                        {
                            **fields,
                            "params": {
                                **(row.params or {}),
                                "skill_audit": skill_audit,
                            },
                        },
                    )
                    await db.commit()

        try:
            await _update_task(
                {
                    "status": StoryTaskStatus.GENERATING.value,
                    "started_at": datetime.now(timezone.utc),
                }
            )
            # 首帧回传 session_id（自动建会话场景前端由此拿到会话 id，对齐 chat）
            _put(
                SseEvent.THINK,
                {"text": "正在阅读技能文档...", "session_id": session_hex},
            )
            graph = story_graph.get()
            graph_input = {
                "idea": idea,
                "style_key": style_key,
                "params_snapshot": params_snapshot,
                "history_lines": history_lines,
                "images": images or [],
                "continuation_prefix": self._continuation_context(continuation_prefix),
            }
            config = {"configurable": {"session_id": session_hex}}
            async for mode, payload in graph.astream(
                graph_input, config, stream_mode=["custom", "updates"]
            ):
                if mode == "custom":
                    # 图内 get_stream_writer 外发的编排事件：think/answer 映射
                    # 为帧，audit 仅更新本地审计快照（不转发给前端）
                    if not isinstance(payload, dict):
                        continue
                    kind = payload.get("type")
                    if kind == "think":
                        text = payload.get("text", "")
                        if text:
                            _put(
                                SseEvent.THINK,
                                {"text": text, "session_id": session_hex},
                            )
                    elif kind == "answer":
                        delta = payload.get("delta", "")
                        if delta:
                            answer_parts.append(delta)
                            _put(SseEvent.ANSWER, {"delta": delta})
                    elif kind == "audit":
                        audit = payload.get("skill_audit")
                        if isinstance(audit, dict):
                            skill_audit = audit
                elif mode == "updates":
                    # 终态回传：图返回的 skill_audit 以最后一次为准
                    for update in (payload or {}).values():
                        if not isinstance(update, dict):
                            continue
                        audit = update.get("skill_audit")
                        if isinstance(audit, dict):
                            skill_audit = audit

            # 续写场景须把已产出的前缀拼回全文再做双轨剥离
            full_text = f"{continuation_base}{''.join(answer_parts)}"
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
            logger.info(
                f"[STORY] 剧本生成完成 session={session_hex} "
                f"rounds={skill_audit.get('tool_rounds')} "
                f"files_read={skill_audit.get('files_read')} "
                f"skipped_skill_read={skill_audit.get('skipped_skill_read')}"
            )
            await _update_task_params(
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
                    "keyframes": track.keyframes,
                    "cards_ok": track.ok,
                    "cards_error": track.error,
                    "params": params_snapshot,
                },
            )
        except asyncio.CancelledError:
            # 用户停止：半截内容落库 stopped（保留可查，续写前缀不丢）
            partial = f"{continuation_base}{''.join(answer_parts)}"
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
                _update_task_params(
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
            partial = f"{continuation_base}{''.join(answer_parts)}"
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
                _update_task_params(
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
                or project.status == StoryProjectStatus.DELETED
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
            # 关键帧逐条落库（kind='keyframe'，关键帧结构化数据挂 params）
            if track.keyframes:
                story_session = await SessionRepository(db).get(session_id)
                for kf in track.keyframes:
                    seq = await message_repo.next_sequence(session_id)
                    await message_repo.create(
                        message_id=uuid7(),
                        session_id=session_id,
                        role=ChatRole.ASSISTANT.value,
                        sequence=seq,
                        kind=StoryMessageKind.KEYFRAME.value,
                        content=f"关键帧 {kf['scene_no']}-{kf['shot_no']}：{kf['name']}",
                        prompt=kf.get("prompt"),
                        params={
                            KEYFRAME_DATA_KEY: kf,
                            "generation_task_id": gen_task_id.hex,
                            **params_snapshot,
                        },
                    )
                if story_session is not None:
                    await SessionRepository(db).touch(
                        story_session,
                        message_delta=len(track.keyframes),
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
