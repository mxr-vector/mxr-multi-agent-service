"""
AI 问答服务层：会话管理（ChatSessionService）与流式问答（ChatCompletionService）。

设计要点：
- 问答历史为个人数据：所有查询按 user_id 等值收敛，他人会话按不存在处理
  （不泄露存在性）；检索来源已由消息级 kb_ids 快照确立，与部门无关；
- 业务表（rag.chat_sessions/chat_messages）是展示与统计的事实源，
  checkpointer 仅服务图运行时，本层不直接读写 checkpoint 表；
- 写库时序（崩溃可恢复）：user 消息（含 kb_ids 快照）→ assistant 占位
  （generating）→ 流结束更新终态（done/stopped/failed）+ 会话计数刷新；
- 停止生成：模块级 {session_id_hex: asyncio.Task} 注册表，stop 即 cancel
  （取消沿 astream → langchain → httpx 传播，推理侧即刻中止），半截内容落库
  stopped；同会话在途任务未结束时新提问互斥拒绝；
- SSE 帧为标准 id/event/data 三字段，id 为会话内事件单调序号。
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage
from uuid_utils.compat import uuid7

from agent.constants.enums.chat import ChatMessageStatus, ChatRole, SseEvent
from agent.prompts.chat import TITLE_PROMPT
from database.postgre_client import get_session
from database.rag.chat import ChatMessageRepository, ChatSessionRepository
from database.rag.document import DocumentRepository
from database.rag.knowledge_base import KnowledgeBaseRepository
from entity.rag.chat import ChatSession
from exception.bad_except import bad_except
from service.rag.knowledge_base import KnowledgeBaseService
from utils.env import ENV
from utils.logger import logger
from utils.page import PageResult, build_page_result
from utils.user_context import UserContext

# 在途生成任务注册表（强引用 + done 回调清除；key 为 session_id hex）
_generation_tasks: dict[str, asyncio.Task] = {}

# 标题摘要等旁路后台任务的强引用集合（防 create_task 产物被 GC 提前回收）
_side_tasks: set[asyncio.Task] = set()

# 标题摘要生成超时（秒），超时回落首问截断
_TITLE_TIMEOUT_SECONDS = 15
# 标题回落截断长度
_TITLE_FALLBACK_LENGTH = 30

# 相似度分级阈值（rerank 得分口径）：>=high high / >=medium medium / 其余 low
_SIMILARITY_HIGH = 0.75
_SIMILARITY_MEDIUM = 0.5


def _similarity_level(score: float) -> str:
    """按 rerank 得分分级为 high/medium/low（展示用）。"""
    if score >= _SIMILARITY_HIGH:
        return "high"
    if score >= _SIMILARITY_MEDIUM:
        return "medium"
    return "low"


async def _enrich_sources(sources: list[dict]) -> list[dict]:
    """对图层 sources 快照做展示级富化（零 N+1）。

    - document_name/kb_name：按去重 id 各一次批量回查回填（实体已删时为 None）；
    - similarity_percent：rerank 得分转 0–100 整数（截断到区间）；
    - similarity_level：按阈值分级。
    无候选时直接返回空列表，不发起任何查询。
    """
    if not sources:
        return []
    doc_ids = list({s["document_id"] for s in sources if s.get("document_id")})
    kb_ids = list(
        {s["knowledge_base_id"] for s in sources if s.get("knowledge_base_id")}
    )
    async with get_session() as session:
        doc_names = await DocumentRepository(session).list_names_by_ids(doc_ids)
        kb_names = await KnowledgeBaseRepository(session).list_names_by_ids(kb_ids)
    enriched = []
    for item in sources:
        score = item.get("score")
        percent = None
        level = None
        if isinstance(score, (int, float)):
            percent = max(0, min(100, round(score * 100)))
            level = _similarity_level(score)
        enriched.append(
            {
                **item,
                "document_name": doc_names.get(item.get("document_id")),
                "kb_name": kb_names.get(item.get("knowledge_base_id")),
                "similarity_percent": percent,
                "similarity_level": level,
            }
        )
    return enriched


def _sse_frame(event_id: int, event: SseEvent, data) -> str:
    """构造标准 SSE 帧：id / event / data 三字段，data 为 JSON 序列化内容。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"id: {event_id}\nevent: {event.value}\ndata: {payload}\n\n"


def _spawn_side_task(coro) -> None:
    """挂旁路后台任务并持强引用（对齐 routers/rag/document.py 的模式）。"""
    task = asyncio.create_task(coro)
    _side_tasks.add(task)
    task.add_done_callback(_side_tasks.discard)


class ChatSessionService:
    """会话业务层：创建、属主校验、列表/详情/历史/统计、删除与清空。"""

    async def _assert_owned(
        self, repo: ChatSessionRepository, session_id: uuid.UUID, ctx: UserContext
    ) -> ChatSession:
        """属主校验收口：不存在 / 已删除 / 非本人一律同文案拒绝。"""
        chat_session = await repo.get(session_id)
        if (
            chat_session is None
            or chat_session.status == "deleted"
            or (ctx.user_id is not None and chat_session.user_id != ctx.user_id)
        ):
            bad_except(f"会话不存在: {session_id.hex}")
        return chat_session

    async def create(self, ctx: UserContext) -> dict:
        """创建会话：应用端生成 uuid7 id（兼作 checkpointer thread_id），占位标题。"""
        if not ctx.user_id:
            bad_except("问答会话仅支持用户通道创建")
        async with get_session() as session:
            chat_session = await ChatSessionRepository(session).create(
                session_id=uuid7(),
                user_id=ctx.user_id,
            )
            await session.commit()
            return chat_session.to_dict()

    async def list(self, ctx: UserContext, page: int = 1, size: int = 20) -> PageResult:
        """分页列出本人未删除会话，按最后消息时间倒序。"""
        if not ctx.user_id:
            return build_page_result([], 0, page, size)
        async with get_session() as session:
            sessions, total = await ChatSessionRepository(session).list(
                ctx.user_id, page=page, size=size
            )
            items = [chat_session.to_dict() for chat_session in sessions]
            return build_page_result(items, total, page, size)

    async def get(self, ctx: UserContext, session_id: uuid.UUID) -> dict:
        """会话详情（仅属主可见）。"""
        async with get_session() as session:
            chat_session = await self._assert_owned(
                ChatSessionRepository(session), session_id, ctx
            )
            return chat_session.to_dict()

    async def messages(
        self, ctx: UserContext, session_id: uuid.UUID, page: int = 1, size: int = 50
    ) -> PageResult:
        """会话消息历史（仅属主可见），按 sequence 升序分页；数据全部来自业务表。"""
        async with get_session() as session:
            await self._assert_owned(ChatSessionRepository(session), session_id, ctx)
            messages, total = await ChatMessageRepository(session).list(
                session_id, page=page, size=size
            )
            items = [message.to_dict() for message in messages]
            return build_page_result(items, total, page, size)

    async def stats(self, ctx: UserContext) -> dict:
        """本人会话总数 / 消息总数统计。"""
        if not ctx.user_id:
            return {"total_sessions": 0, "total_messages": 0}
        async with get_session() as session:
            return await ChatSessionRepository(session).stats(ctx.user_id)

    async def delete(self, ctx: UserContext, session_id: uuid.UUID) -> None:
        """删除会话：先取消在途任务，业务表软删，并同步删除 checkpoint thread。"""
        cancel_generation(session_id.hex)
        async with get_session() as session:
            repo = ChatSessionRepository(session)
            chat_session = await self._assert_owned(repo, session_id, ctx)
            await repo.soft_delete(chat_session)
            await session.commit()
        await self._delete_thread(session_id)

    async def delete_all(self, ctx: UserContext) -> int:
        """清空本人全部会话：软删 + 逐一清理 checkpoint thread，返回删除数。"""
        if not ctx.user_id:
            return 0
        async with get_session() as session:
            deleted_ids = await ChatSessionRepository(session).soft_delete_all(
                ctx.user_id
            )
            await session.commit()
        for session_id in deleted_ids:
            cancel_generation(session_id.hex)
            await self._delete_thread(session_id)
        return len(deleted_ids)

    @staticmethod
    async def _delete_thread(session_id: uuid.UUID) -> None:
        """删除该会话的 checkpoint thread；checkpointer 未装配/失败仅告警不阻断。"""
        try:
            from agent.checkpoints.postgres import get_checkpointer

            await get_checkpointer().adelete_thread(session_id.hex)
        except Exception as exc:
            logger.warning(
                f"[CHAT] 清理 checkpoint thread 失败 {session_id.hex}: {exc}"
            )


def cancel_generation(session_id_hex: str) -> bool:
    """取消会话在途生成任务（幂等）：有在途任务返回 True，否则 False。"""
    task = _generation_tasks.get(session_id_hex)
    if task is None or task.done():
        return False
    task.cancel()
    return True


async def reset_stale_generating() -> int:
    """启动清扫：残留 generating 消息统一置为 failed（进程崩溃后的恢复路径）。"""
    async with get_session() as session:
        count = await ChatMessageRepository(session).reset_stale_generating()
        await session.commit()
    if count:
        logger.warning(f"[CHAT] 启动清扫：{count} 条残留 generating 消息已置为 failed")
    return count


class ChatCompletionService:
    """流式问答业务层：会话/消息写库时序、图执行事件映射、停止与标题摘要。"""

    def __init__(self) -> None:
        self._session_service = ChatSessionService()
        self._kb_service = KnowledgeBaseService()

    async def stream(
        self,
        ctx: UserContext,
        question: str,
        session_id: uuid.UUID | None = None,
        kb_ids: list[str] | None = None,
        use_web_search: bool = False,
        reasoning_effort: str | None = None,
    ):
        """
        发起一轮流式问答，返回 SSE 帧异步生成器。

        进入流之前完成：会话校验/自动创建、同会话互斥、kb 范围解析、
        user 消息与 assistant 占位落库；随后图执行在独立 task 中运行，
        事件经 asyncio.Queue 桥接到 SSE 生成器（cancel 只打断图执行，
        不影响收尾帧下发）。
        """
        question = (question or "").strip()
        if not question:
            bad_except("问题内容不能为空")
        if not ctx.user_id:
            bad_except("流式问答仅支持用户通道调用")

        # 会话解析：缺省自动创建；显式传入须为本人未删会话
        async with get_session() as session:
            repo = ChatSessionRepository(session)
            if session_id is None:
                chat_session = await repo.create(
                    session_id=uuid7(),
                    user_id=ctx.user_id,
                )
                await session.commit()
            else:
                chat_session = await self._session_service._assert_owned(
                    repo, session_id, ctx
                )
            resolved_session_id: uuid.UUID = chat_session.id
            is_first_turn = chat_session.message_count == 0

        session_hex = resolved_session_id.hex

        # 同会话生成互斥：在途任务未结束时拒绝新提问
        existing = _generation_tasks.get(session_hex)
        if existing is not None and not existing.done():
            bad_except("上一条回答尚未完成，请稍候或先停止生成")

        # kb 检索范围解析（消息级）：显式传入优先，否则解析缺省可见范围
        resolved_kb_ids = (
            kb_ids if kb_ids else await self._kb_service.list_visible_ids(ctx)
        )

        # 写库时序：user 消息（kb_ids 快照）→ assistant 占位（generating）
        now = datetime.now(timezone.utc)
        async with get_session() as session:
            session_repo = ChatSessionRepository(session)
            message_repo = ChatMessageRepository(session)
            chat_session = await session_repo.get(resolved_session_id)
            user_seq = await message_repo.next_sequence(resolved_session_id)
            await message_repo.append(
                session_id=resolved_session_id,
                role=ChatRole.USER.value,
                sequence=user_seq,
                content=question,
                kb_ids=resolved_kb_ids,
                status=ChatMessageStatus.DONE.value,
            )
            assistant_message = await message_repo.append(
                session_id=resolved_session_id,
                role=ChatRole.ASSISTANT.value,
                sequence=user_seq + 1,
                status=ChatMessageStatus.GENERATING.value,
            )
            assistant_message_id = assistant_message.id
            await session_repo.touch(chat_session, message_delta=1, last_message_at=now)
            await session.commit()

        queue: asyncio.Queue[str | None] = asyncio.Queue()
        task = asyncio.create_task(
            self._generate(
                queue=queue,
                session_id=resolved_session_id,
                assistant_message_id=assistant_message_id,
                question=question,
                kb_ids=resolved_kb_ids,
                use_web_search=use_web_search,
                reasoning_effort=reasoning_effort,
                is_first_turn=is_first_turn,
            )
        )
        _generation_tasks[session_hex] = task
        task.add_done_callback(
            lambda done_task: _generation_tasks.pop(session_hex, None)
        )

        async def _frames():
            try:
                while True:
                    frame = await queue.get()
                    if frame is None:
                        break
                    yield frame
            finally:
                # 客户端断连（生成器被提前关闭）时同步取消图执行，
                # 避免模型继续推理产生孤儿任务；半截内容由取消分支落库 stopped
                if not task.done():
                    task.cancel()

        return _frames()

    async def _generate(
        self,
        queue: asyncio.Queue,
        session_id: uuid.UUID,
        assistant_message_id: uuid.UUID,
        question: str,
        kb_ids: list[str],
        use_web_search: bool,
        reasoning_effort: str | None,
        is_first_turn: bool,
    ) -> None:
        """图执行协程：astream 事件映射为 SSE 帧入队，终态落库并发收尾帧。"""
        from agent.constants.enums.chat import ChatNode
        from agent.sub.chat_graph import get_chat_graph

        session_hex = session_id.hex
        event_id = 0
        answer_parts: list[str] = []
        think_parts: list[str] = []
        sources: list[dict] = []
        metrics: dict = {}
        started_at = time.monotonic()

        def _put(event: SseEvent, data) -> None:
            nonlocal event_id
            event_id += 1
            queue.put_nowait(_sse_frame(event_id, event, data))

        try:
            graph = get_chat_graph()
            config = {"configurable": {"thread_id": session_hex}}
            graph_input = {
                "messages": [HumanMessage(content=question)],
                "question": question,
                "kb_ids": kb_ids,
                "use_web_search": use_web_search,
                "reasoning_effort": reasoning_effort,
            }
            # 首帧回传 session_id（自动建会话场景前端由此拿到会话 id）
            _put(SseEvent.THINK, {"text": "正在理解问题...", "session_id": session_hex})

            async for mode, payload in graph.astream(
                graph_input, config, stream_mode=["updates", "messages"]
            ):
                if mode == "messages":
                    chunk, metadata = payload
                    # 仅放行 respond 节点（含其内部子调用）的答案 token；
                    # condense 改写与子图仲裁模型的 token 不外流
                    if metadata.get("langgraph_node") != ChatNode.RESPOND.value:
                        continue
                    delta = chunk.content if isinstance(chunk.content, str) else ""
                    if delta:
                        answer_parts.append(delta)
                        _put(SseEvent.ANSWER, {"delta": delta})
                elif mode == "updates":
                    for node_name, update in (payload or {}).items():
                        if not isinstance(update, dict):
                            continue
                        if node_name == ChatNode.CONDENSE.value:
                            standalone = update.get("standalone_question")
                            if standalone and standalone != question:
                                text = f"已将问题改写为：{standalone}"
                            else:
                                text = "正在检索知识库..."
                            think_parts.append(text)
                            _put(SseEvent.THINK, {"text": text})
                        elif node_name == ChatNode.RAG_RETRIEVE.value:
                            count = len(update.get("reranked_docs") or [])
                            text = f"已检索并精选 {count} 条相关内容，正在组织回答..."
                            think_parts.append(text)
                            _put(SseEvent.THINK, {"text": text})
                        elif node_name == ChatNode.RESPOND.value:
                            sources = update.get("sources") or []
                            metrics = update.get("metrics") or {}

            # 图执行总耗时，并对 sources 做展示级富化后再外发
            metrics = {
                **metrics,
                "duration_ms": round((time.monotonic() - started_at) * 1000),
            }
            sources = await _enrich_sources(sources)
            _put(SseEvent.SOURCES, sources)
            answer = "".join(answer_parts)
            await self._finalize(
                assistant_message_id,
                session_id,
                status=ChatMessageStatus.DONE,
                content=answer,
                thinking="\n".join(think_parts),
                sources=sources,
                metrics=metrics,
            )
            _put(
                SseEvent.DONE,
                {
                    "session_id": session_hex,
                    "message_id": assistant_message_id.hex,
                    "status": ChatMessageStatus.DONE.value,
                    "metrics": metrics,
                },
            )
            if is_first_turn:
                _spawn_side_task(self._generate_title(session_id, question))
        except asyncio.CancelledError:
            # 用户停止：半截内容落库 stopped（保留已采集的部分指标），done 帧正常收尾
            partial_metrics = {
                **metrics,
                "duration_ms": round((time.monotonic() - started_at) * 1000),
            }
            _spawn_side_task(
                self._finalize(
                    assistant_message_id,
                    session_id,
                    status=ChatMessageStatus.STOPPED,
                    content="".join(answer_parts),
                    thinking="\n".join(think_parts),
                    sources=await _enrich_sources(sources),
                    metrics=partial_metrics,
                )
            )
            _put(
                SseEvent.DONE,
                {
                    "session_id": session_hex,
                    "message_id": assistant_message_id.hex,
                    "status": ChatMessageStatus.STOPPED.value,
                    "metrics": partial_metrics,
                },
            )
            raise
        except Exception as exc:
            logger.exception(f"[CHAT] 问答生成失败 session={session_hex}: {exc}")
            await self._finalize(
                assistant_message_id,
                session_id,
                status=ChatMessageStatus.FAILED,
                content="".join(answer_parts),
                thinking="\n".join(think_parts),
                sources=sources,
                metrics={
                    **metrics,
                    "duration_ms": round((time.monotonic() - started_at) * 1000),
                },
                error=str(exc),
            )
            _put(SseEvent.ERROR, {"msg": "回答生成失败，请稍后重试"})
        finally:
            queue.put_nowait(None)

    @staticmethod
    async def _finalize(
        assistant_message_id: uuid.UUID,
        session_id: uuid.UUID,
        status: ChatMessageStatus,
        content: str,
        thinking: str,
        sources: list[dict],
        metrics: dict | None = None,
        error: str | None = None,
    ) -> None:
        """更新 assistant 占位行终态（含推理指标），并刷新会话计数与最后消息时间。"""
        async with get_session() as session:
            await ChatMessageRepository(session).update_completion(
                assistant_message_id,
                status=status.value,
                content=content,
                thinking=thinking,
                sources=sources,
                metrics=metrics,
                error=error,
            )
            session_repo = ChatSessionRepository(session)
            chat_session = await session_repo.get(session_id)
            if chat_session is not None:
                await session_repo.touch(
                    chat_session,
                    message_delta=1,
                    last_message_at=datetime.now(timezone.utc),
                )
            await session.commit()

    @staticmethod
    async def _generate_title(session_id: uuid.UUID, question: str) -> None:
        """首轮完成后异步生成会话标题：rewrite_model 一句摘要，失败/超时回落截断。"""
        fallback = question[:_TITLE_FALLBACK_LENGTH]
        title = fallback
        try:
            from model.compression.factory import build_compression_model

            response = await asyncio.wait_for(
                build_compression_model().ainvoke(
                    [
                        {
                            "role": ChatRole.USER.value,
                            "content": TITLE_PROMPT.format(question=question),
                        }
                    ]
                ),
                timeout=_TITLE_TIMEOUT_SECONDS,
            )
            generated = (response.content or "").strip().strip('"')
            if generated:
                title = generated
        except Exception as exc:
            logger.warning(f"[CHAT] 标题摘要生成失败，回落截断 {session_id.hex}: {exc}")
        async with get_session() as session:
            await ChatSessionRepository(session).update_title(session_id, title)
            await session.commit()
