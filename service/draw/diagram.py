"""
绘图模块业务层：多模态 Mermaid 生成（SSE）、会话管理、图表版本链。

- 生成链路对齐 service.rag.chat 的编排骨架：会话校验/自动创建 → 同会话在途
  互斥 → user 消息 + assistant 占位落库 → 模型 astream 在独立 Task 中运行，
  帧经 asyncio.Queue 桥接到 SSE 生成器（客户端断连时 cancel 图执行）；
- 一期为单轮"输入 → Mermaid"直调模型（不建 LangGraph 子图，见 design.md D5）；
- 图表版本 append-only：AI 生成/用户编辑保存均插入新版本（parent_id 指向基线），
  永不覆盖既有版本记录。
"""

import asyncio
import base64
import re
import time
import uuid
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage
from uuid_utils.compat import uuid7

from agent.constants.enums.chat import (
    ChatMessageStatus,
    ChatRole,
    SseEvent,
)
from agent.constants.enums.draw import DrawSourceType
from agent.prompts.draw import (
    DRAW_REVISE_CONTEXT,
    DRAW_SYSTEM_PROMPT,
    MERMAID_DIAGRAM_TYPES,
)
from database.draw.diagram import (
    DrawDiagramVersionRepository,
    DrawMessageRepository,
    DrawSessionRepository,
)
from database.postgre_client import get_session
from exception.bad_except import bad_except
from model.visual.factory import build_visual_model
from utils.env import ENV
from core.config_snapshot import CFG
from utils.logger import logger
from utils.stream_runtime import GenerationTaskRegistry, sse_frame, spawn_side_task

# 上传图片后缀白名单 -> data URI 的 MIME 类型（仅图片，多模态 image_url 消费）
IMAGE_EXTENSION_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}

# 绘图上传图片子目录（upload 端点写入与 _image_to_data_uri 读取的同一范围）
_IMAGE_UPLOAD_SUBDIR = "draw/upload"

# drawio XML 入库长度上限（字符）：正常图表远小于该值，超限视为异常输入
DRAWIO_XML_MAX_CHARS = 2_000_000

# 会话标题取首问截断长度
_TITLE_MAX_CHARS = 30

# 思考阶段 think 心跳间隔（秒）：visual 推理模型（如 step-3.7-flash）带图时会先
# 进行长时间思考，期间流式 chunk 的 content 全为空串（思考 token 不回传正文），
# 不发帧会让前端一直停留在"正在生成图表…"；按此间隔发送带耗时的 think 帧
# 以呈现进展并保活连接
_THINK_HEARTBEAT_SECONDS = 3

# Mermaid 代码块提取（```mermaid ... ```，容忍前后杂散文本）
_MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)

# 会话级在途生成任务注册表（占位式互斥，公共实现见 utils/stream_runtime.py）
_generation_registry = GenerationTaskRegistry(
    "上一张图尚未生成完成，请稍候或先停止生成"
)


def cancel_generation(session_hex: str) -> bool:
    """取消指定会话的在途生成任务；无在途任务返回 False（幂等）。"""
    return _generation_registry.cancel(session_hex)


async def reset_stale_generating() -> int:
    """启动清扫：残留 generating 消息统一置为 failed（进程崩溃后的恢复路径）。"""
    async with get_session() as session:
        count = await DrawMessageRepository(session).reset_stale_generating()
        await session.commit()
    if count:
        logger.warning(f"[DRAW] 启动清扫：{count} 条残留 generating 消息已置为 failed")
    return count


def extract_mermaid(text: str) -> str | None:
    """从模型回复中提取 Mermaid 代码块并做基础校验。

    校验规则：代码块存在且非空、首个非空行以受支持图型声明开头
    （白名单见 agent.prompts.draw.MERMAID_DIAGRAM_TYPES）；
    不合法返回 None（调用方仅存文本回复、不建版本）。
    """
    match = _MERMAID_BLOCK_RE.search(text or "")
    if match is None:
        return None
    source = match.group(1).strip()
    if not source:
        return None
    first_line = source.splitlines()[0].strip()
    if not any(first_line.startswith(t) for t in MERMAID_DIAGRAM_TYPES):
        return None
    return source


def _image_to_data_uri(relative_path: str) -> str:
    """读取绘图上传子目录下的图片文件，转为 base64 data URI。

    relative_path 为 upload 端点返回的 data/ 下相对路径（如 draw/upload/xxx.png）；
    路径归一化后必须仍位于 draw/upload 子目录内：目录穿越封死，
    也不允许借路径引用上传根目录下的其他文件（如他人头像）。
    """
    upload_root = ENV.upload_dir.resolve()
    image_root = (upload_root / _IMAGE_UPLOAD_SUBDIR).resolve()
    path = (upload_root / relative_path).resolve()
    if not path.is_relative_to(image_root):
        bad_except("非法的图片路径")
    if not path.is_file():
        bad_except("图片文件不存在或已被清理，请重新上传")
    ext = path.suffix.lstrip(".").lower()
    mime = IMAGE_EXTENSION_MIME.get(ext)
    if mime is None:
        bad_except(f"不支持的图片类型: {ext}")
    encoded = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{encoded}"


class DrawSessionService:
    """绘图会话查询/删除业务层：属主校验收口。"""

    async def _assert_owned(self, repo, session_id: uuid.UUID, ctx):
        """会话须存在、未删除且归属当前用户，否则业务失败。"""
        draw_session = await repo.get(session_id)
        if (
            draw_session is None
            or draw_session.status == "deleted"
            or draw_session.user_id != ctx.user_id
        ):
            bad_except("绘图会话不存在")
        return draw_session

    async def list(self, ctx, page: int, size: int) -> tuple[list[dict], int]:
        """分页列出本人会话，按最后消息时间倒序。"""
        if not ctx.user_id:
            bad_except("绘图会话仅支持用户通道调用")
        async with get_session() as session:
            items, total = await DrawSessionRepository(session).list(
                ctx.user_id, page, size
            )
            return [item.to_dict() for item in items], total

    async def messages(
        self, ctx, session_id: uuid.UUID, page: int, size: int
    ) -> "tuple[list[dict], int]":
        """会话消息历史（按 sequence 升序分页），须为本人会话。

        注：返回注解用字符串形式，避免类作用域内被上方 `list` 方法遮蔽。
        """
        async with get_session() as session:
            await self._assert_owned(DrawSessionRepository(session), session_id, ctx)
            items, total = await DrawMessageRepository(session).list(
                session_id, page, size
            )
            return [item.to_dict() for item in items], total

    async def versions(self, ctx, session_id: uuid.UUID) -> "list[dict]":
        """会话图表版本链（创建时间升序），须为本人会话；不携带 drawio_xml。"""
        async with get_session() as session:
            await self._assert_owned(DrawSessionRepository(session), session_id, ctx)
            items = await DrawDiagramVersionRepository(session).list_by_session(
                session_id
            )
            return [item.to_dict() for item in items]

    async def version_detail(self, ctx, version_id: uuid.UUID) -> dict:
        """版本详情（携带 drawio_xml，供编辑器加载），须为本人会话下的版本。"""
        async with get_session() as session:
            version = await DrawDiagramVersionRepository(session).get(version_id)
            if version is None:
                bad_except("图表版本不存在")
            await self._assert_owned(
                DrawSessionRepository(session), version.session_id, ctx
            )
            return version.to_dict(with_xml=True)

    async def delete(self, ctx, session_id: uuid.UUID) -> None:
        """删除会话：校验属主后取消在途任务，同事务物理删除消息与版本记录（预览/图片文件不追删）。"""
        async with get_session() as session:
            repo = DrawSessionRepository(session)
            draw_session = await self._assert_owned(repo, session_id, ctx)
            # 取消在途生成必须在校验属主之后：in_flight/cancel 的差异化报错
            # 会向未授权用户泄露他人会话的存在与运行状态
            if _generation_registry.in_flight(session_id.hex):
                bad_except("该会话正在生成中，请先停止生成")
            _generation_registry.cancel(session_id.hex)
            await DrawMessageRepository(session).delete_by_session(session_id)
            await DrawDiagramVersionRepository(session).delete_by_session(session_id)
            await repo.delete(draw_session)
            await session.commit()

    async def save_edit(
        self,
        ctx,
        session_id: uuid.UUID,
        parent_id: uuid.UUID,
        drawio_xml: str,
        preview_file: str | None,
    ) -> dict:
        """drawio 编辑保存：append-only 新增 user 来源版本，基线版本保持不变。

        XML 基本格式与长度校验不通过时拒绝保存、不产生版本记录；
        新版本冗余保存基线版本的 mermaid_source（供后续 AI 再生成参考）。
        """
        drawio_xml = (drawio_xml or "").strip()
        if not drawio_xml:
            bad_except("图表内容不能为空")
        if len(drawio_xml) > DRAWIO_XML_MAX_CHARS:
            bad_except("图表内容超过大小上限，无法保存")
        # 基本格式校验：drawio 导出的 XML 根节点为 <mxfile> 或 <mxGraphModel>
        if not drawio_xml.startswith("<") or (
            "<mxfile" not in drawio_xml[:200]
            and "<mxGraphModel" not in drawio_xml[:200]
        ):
            bad_except("图表内容格式不合法")

        async with get_session() as session:
            await self._assert_owned(DrawSessionRepository(session), session_id, ctx)
            version_repo = DrawDiagramVersionRepository(session)
            parent = await version_repo.get(parent_id)
            if parent is None or parent.session_id != session_id:
                bad_except("基线版本不存在")
            version = await version_repo.append(
                session_id=session_id,
                source_type=DrawSourceType.USER.value,
                parent_id=parent_id,
                mermaid_source=parent.mermaid_source,
                drawio_xml=drawio_xml,
                preview_file=preview_file,
            )
            await session.commit()
            return version.to_dict()


class DrawCompletionService:
    """多模态生成业务层：写库时序、模型流式事件映射、停止与终态落库。"""

    def __init__(self) -> None:
        self._session_service = DrawSessionService()

    async def stream(
        self,
        ctx,
        question: str,
        session_id: uuid.UUID | None = None,
        image_file: str | None = None,
        base_version_id: uuid.UUID | None = None,
    ):
        """发起一轮流式生成，返回 SSE 帧异步生成器。

        - question 与 image_file 至少其一非空（图片可不附文字，按缺省指令重绘）；
        - base_version_id 为多轮改图基线：注入其 mermaid_source 供模型修改，
          新 AI 版本的 parent_id 指向它。
        """
        question = (question or "").strip()
        if not question and not image_file:
            bad_except("请输入问题描述或上传图片")
        if not ctx.user_id:
            bad_except("绘图问答仅支持用户通道调用")

        # 图片引用在进流前完成校验（含 data URI 预构造，早失败）
        image_data_uri = _image_to_data_uri(image_file) if image_file else None

        # 会话解析：缺省自动创建（标题取首问截断）；显式传入须为本人未删会话
        async with get_session() as session:
            repo = DrawSessionRepository(session)
            if session_id is None:
                title = (question or "图片重绘")[:_TITLE_MAX_CHARS]
                draw_session = await repo.create(
                    session_id=uuid7(), user_id=ctx.user_id, title=title
                )
                await session.commit()
            else:
                draw_session = await self._session_service._assert_owned(
                    repo, session_id, ctx
                )
            resolved_session_id: uuid.UUID = draw_session.id

        # 基线版本须归属当前会话：杜绝借他人版本的 mermaid_source 越权读图、
        # 以及新版本 parent_id 指向他人会话污染版本链
        base_mermaid: str | None = None
        if base_version_id is not None:
            async with get_session() as session:
                base_version = await DrawDiagramVersionRepository(session).get(
                    base_version_id
                )
                if (
                    base_version is None
                    or base_version.session_id != resolved_session_id
                ):
                    bad_except("基线版本不存在")
                base_mermaid = base_version.mermaid_source

        session_hex = resolved_session_id.hex

        # 同会话生成互斥：原子占位（检查与注册之间隔着多次 await，占位防并发穿透）
        _generation_registry.acquire(session_hex)

        # 写库时序：user 消息（含图片引用）→ assistant 占位（generating）
        try:
            now = datetime.now(timezone.utc)
            async with get_session() as session:
                session_repo = DrawSessionRepository(session)
                message_repo = DrawMessageRepository(session)
                draw_session = await session_repo.get(resolved_session_id)
                user_seq = await message_repo.next_sequence(resolved_session_id)
                await message_repo.append(
                    session_id=resolved_session_id,
                    role=ChatRole.USER.value,
                    sequence=user_seq,
                    content=question,
                    image_file=image_file,
                    status=ChatMessageStatus.DONE.value,
                )
                assistant_message = await message_repo.append(
                    session_id=resolved_session_id,
                    role=ChatRole.ASSISTANT.value,
                    sequence=user_seq + 1,
                    status=ChatMessageStatus.GENERATING.value,
                )
                assistant_message_id = assistant_message.id
                await session_repo.touch(
                    draw_session, message_delta=1, last_message_at=now
                )
                await session.commit()
        except BaseException:
            # 进流前失败：归还占位，避免会话被永久锁死
            _generation_registry.release(session_hex)
            raise

        queue: asyncio.Queue[str | None] = asyncio.Queue()
        task = asyncio.create_task(
            self._generate(
                queue=queue,
                session_id=resolved_session_id,
                assistant_message_id=assistant_message_id,
                question=question,
                image_data_uri=image_data_uri,
                base_mermaid=base_mermaid,
                base_version_id=base_version_id,
            )
        )
        _generation_registry.register(session_hex, task)

        async def _frames():
            try:
                while True:
                    frame = await queue.get()
                    if frame is None:
                        break
                    yield frame
            finally:
                # 客户端断连时同步取消模型调用，避免孤儿推理任务；
                # 半截内容由取消分支落库 stopped
                if not task.done():
                    task.cancel()

        return _frames()

    async def stop(self, ctx, session_id: uuid.UUID) -> bool:
        """停止会话在途生成（幂等）；仅属主可停止，返回是否实际取消。"""
        if not ctx.user_id:
            bad_except("绘图会话仅支持用户通道调用")
        async with get_session() as session:
            await self._session_service._assert_owned(
                DrawSessionRepository(session), session_id, ctx
            )
        return cancel_generation(session_id.hex)

    def _build_messages(
        self,
        question: str,
        image_data_uri: str | None,
        base_mermaid: str | None,
    ) -> list:
        """构造多模态消息：system 约定 + 可选基线图上下文 + 文本/图片用户消息。"""
        system_parts = [DRAW_SYSTEM_PROMPT]
        if base_mermaid:
            system_parts.append(DRAW_REVISE_CONTEXT.format(mermaid_source=base_mermaid))
        content: list[dict] = []
        text = question or "请识别图片中的图表结构并用 Mermaid 重绘。"
        content.append({"type": "text", "text": text})
        if image_data_uri:
            content.append({"type": "image_url", "image_url": {"url": image_data_uri}})
        return [
            SystemMessage(content="\n\n".join(system_parts)),
            HumanMessage(content=content),
        ]

    async def _generate(
        self,
        queue: asyncio.Queue,
        session_id: uuid.UUID,
        assistant_message_id: uuid.UUID,
        question: str,
        image_data_uri: str | None,
        base_mermaid: str | None,
        base_version_id: uuid.UUID | None,
    ) -> None:
        """模型流式协程：token 映射为 answer 帧入队，终态落库并发收尾帧。"""
        session_hex = session_id.hex
        event_id = 0
        answer_parts: list[str] = []
        started_at = time.monotonic()

        def _put(event: SseEvent, data) -> None:
            nonlocal event_id
            event_id += 1
            queue.put_nowait(sse_frame(event_id, event, data))

        try:
            model = build_visual_model()
            messages = self._build_messages(question, image_data_uri, base_mermaid)
            # 首帧回传 session_id（自动建会话场景前端由此拿到会话 id）
            _put(SseEvent.THINK, {"text": "正在生成图表...", "session_id": session_hex})

            last_think_at = time.monotonic()
            async for chunk in model.astream(messages):
                delta = chunk.content if isinstance(chunk.content, str) else ""
                if delta:
                    answer_parts.append(delta)
                    _put(SseEvent.ANSWER, {"delta": delta})
                elif not answer_parts:
                    # 思考阶段空 content chunk：周期性发 think 心跳（带已耗时）
                    now_mono = time.monotonic()
                    if now_mono - last_think_at >= _THINK_HEARTBEAT_SECONDS:
                        last_think_at = now_mono
                        elapsed = int(now_mono - started_at)
                        _put(
                            SseEvent.THINK,
                            {
                                "text": f"模型思考中…（已 {elapsed} 秒，图片越复杂耗时越长）",
                                "session_id": session_hex,
                            },
                        )

            answer = "".join(answer_parts)
            mermaid_source = extract_mermaid(answer)
            metrics = {
                "model": CFG.visual.model_name,
                "duration_ms": round((time.monotonic() - started_at) * 1000),
            }
            version_id = await self._finalize(
                assistant_message_id,
                session_id,
                status=ChatMessageStatus.DONE,
                content=answer,
                mermaid_source=mermaid_source,
                base_version_id=base_version_id,
            )
            _put(
                SseEvent.DONE,
                {
                    "session_id": session_hex,
                    "message_id": assistant_message_id.hex,
                    "status": ChatMessageStatus.DONE.value,
                    "version_id": version_id,
                    "mermaid_source": mermaid_source,
                    "metrics": metrics,
                },
            )
        except asyncio.CancelledError:
            # 用户停止：半截内容落库 stopped（不提取/不建版本），done 帧正常收尾
            spawn_side_task(
                self._finalize(
                    assistant_message_id,
                    session_id,
                    status=ChatMessageStatus.STOPPED,
                    content="".join(answer_parts),
                    mermaid_source=None,
                    base_version_id=None,
                )
            )
            _put(
                SseEvent.DONE,
                {
                    "session_id": session_hex,
                    "message_id": assistant_message_id.hex,
                    "status": ChatMessageStatus.STOPPED.value,
                    "version_id": None,
                    "mermaid_source": None,
                    "metrics": {
                        "duration_ms": round((time.monotonic() - started_at) * 1000)
                    },
                },
            )
            raise
        except Exception as exc:
            logger.exception(f"[DRAW] 图表生成失败 session={session_hex}: {exc}")
            await self._finalize(
                assistant_message_id,
                session_id,
                status=ChatMessageStatus.FAILED,
                content="".join(answer_parts),
                mermaid_source=None,
                base_version_id=None,
                error=str(exc),
            )
            _put(SseEvent.ERROR, {"msg": "图表生成失败，请检查 VISUAL 模型服务后重试"})
        finally:
            queue.put_nowait(None)

    @staticmethod
    async def _finalize(
        assistant_message_id: uuid.UUID,
        session_id: uuid.UUID,
        status: ChatMessageStatus,
        content: str,
        mermaid_source: str | None,
        base_version_id: uuid.UUID | None,
        error: str | None = None,
    ) -> str | None:
        """同事务：更新 assistant 占位行终态 + 生成成功时插入 AI 版本记录。

        返回新版本 id（hex）；未提取到合法 Mermaid 时不建版本、返回 None
        （前端据此提示生成失败并提供重新生成入口）。
        """
        async with get_session() as session:
            await DrawMessageRepository(session).update_completion(
                assistant_message_id,
                status=status.value,
                content=content,
                error=error,
            )
            version_id: str | None = None
            if status is ChatMessageStatus.DONE and mermaid_source:
                version = await DrawDiagramVersionRepository(session).append(
                    session_id=session_id,
                    source_type=DrawSourceType.AI.value,
                    message_id=assistant_message_id,
                    parent_id=base_version_id,
                    mermaid_source=mermaid_source,
                )
                version_id = version.id.hex
            session_repo = DrawSessionRepository(session)
            draw_session = await session_repo.get(session_id)
            if draw_session is not None:
                await session_repo.touch(
                    draw_session,
                    message_delta=1,
                    last_message_at=datetime.now(timezone.utc),
                )
            await session.commit()
            return version_id

