"""
Chat 问答父图（LangGraph）—— 多轮编排 + Agentic 检索工具 + 流式生成。

职责划分：
- 父图负责多轮状态管理（checkpointer 恢复 messages 历史）、将历史注入系统
  提示供对话模型自主消解指代、流式生成答案与结构化 sources；
- 检索与问题改写均由对话模型自主决策：模型绑定
  knowledge_base_search / web_search 工具（见 agent.tools.rag_tools）后进入
  工具调用循环，模型自行判断当前问题是否依赖历史指代、需要时以改写后的
  独立查询调用检索工具；混合召回/反思自纠错/重排序均在工具内部完成。

节点（全部 async）：
- respond：Agentic 回答节点——系统提示注入对话历史与可用知识库 id，
  bind_tools 检索工具后逐轮调用对话模型：模型返回 tool_calls 则执行对应
  工具（ToolMessage 回填后继续），无 tool_calls 则流式输出最终答案并构造
  结构化 sources；checkpointer 无历史（TTL 已清理/存量会话）时回落业务表
  rag.chat_messages 读最近 N 条作为历史（业务表是事实源）。工具结果按
  全局编号 [n] 引用，与 sources.index 严格对应。该节点内的模型调用 token
  经 astream(stream_mode="messages") 外流，检索进度经 stream_mode="custom" 外发。

入口：模块级单例 `chat_graph = ChatGraph()`，通过 `chat_graph.get()` 惰性编译
（依赖 lifespan 已装配的 checkpointer，模块 import 期不建连不编译）。
调用时 config 须携带 `{"configurable": {"thread_id": session_id_hex}}`；
每轮输入 state 为 `{messages: [HumanMessage(question)], question, kb_ids,
use_web_search, reasoning_effort}`。
终态含 `answer`（字符串）与 `sources`（每项
`{text, source, score, knowledge_base_id, chapter_title, document_id, chunk_id}`）。
"""

import hashlib
import uuid
from typing import List, Tuple

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph

from agent.constants.enums.chat import ChatNode, ChatRole
from agent.prompts.chat import AGENT_PROMPT, AGENT_TOOLS_GUIDANCE
from agent.tools.rag_tools import (
    TOOL_IMPLS,
    ToolOutcome,
    chunk_read,
    entity_relation_lookup,
    kb_wiki_lookup,
    knowledge_base_search,
    web_search,
)
from exception.bad_except import BadException
from model.chat.factory import build_chat_model
from core.config_snapshot import CFG
from utils.logger import logger
from utils.env import ENV
from utils.token_count import count_messages_tokens, count_tokens

# 输入预算安全边际：context_window 的固定比例（覆盖 tiktoken 估算偏差）
_INPUT_BUDGET_SAFETY_MARGIN = 0.10
# 历史文本行级固定开销（行分隔符/角色标记）
_LINE_FIXED_TOKENS = 2

# count_messages_tokens（tiktoken 同步 CPU 编码）的单消息结果缓存：
# 预算守卫在循环里对同内容消息反复编码（_ensure_within_budget 每轮全量重估），
# key 用 (模型名, 消息角色, role+content 哈希)，同内容重复编码直接命中；
# 缓存有界——条数超上限整体清空，防止长会话下无界增长
_MESSAGE_TOKEN_CACHE_MAX_ENTRIES = 4096
_message_token_cache: dict[tuple, int] = {}


def _message_token_cost(model_name: str, message: BaseMessage) -> int:
    """单条消息 token 估算（进程内缓存）：等价于 count_messages_tokens(model, [m])。"""
    digest = hashlib.md5(
        (
            f"{type(message).__name__}:{getattr(message, 'content', None)!r}"
        ).encode("utf-8")
    ).hexdigest()
    key = (model_name, digest)
    cached = _message_token_cache.get(key)
    if cached is not None:
        return cached
    cost = count_messages_tokens(model_name, [message])
    if len(_message_token_cache) >= _MESSAGE_TOKEN_CACHE_MAX_ENTRIES:
        _message_token_cache.clear()
    _message_token_cache[key] = cost
    return cost


def _messages_tokens_cached(model_name: str, messages: List[BaseMessage]) -> int:
    """消息列表 token 估算：按缓存的单消息成本求和（与全量估算口径一致）。"""
    return sum(_message_token_cost(model_name, message) for message in messages)


class ChatState(MessagesState):
    """父图状态：messages 跨轮累积（checkpointer 持久化），其余字段每轮覆盖。"""

    # 本轮原始问题（改写决策由 respond 节点内对话模型自主决定）
    question: str
    # 本轮检索范围（hex 无连字符列表，消息级，由调用方解析后传入）
    kb_ids: List[str]
    # 联网搜索开关（True 时绑定 web_search 工具，模型可见可调用）
    use_web_search: bool
    # 本轮思考强度（reasoning_effort，缺省用模块级默认模型）
    reasoning_effort: str | None
    # 推理复杂度指标（respond 节点工具轮/检索指标 + token/模型，服务层补齐耗时）
    metrics: dict
    # 最终答案与结构化来源
    answer: str
    sources: List[dict]


class ChatGraph:
    """Chat 父图封装：持有编译单例（get() 惰性编译）。

    模型不在构造期固化：各节点每次调用时按当前配置快照现造，
    以便模型配置热更新自下一请求生效（图结构与配置无关，无需重编译）。
    """

    def __init__(self):
        # 编译后的父图缓存（首次 get() 时装配 checkpointer 后编译）
        self._compiled = None

    # ---------- 辅助 ----------
    @staticmethod
    def _format_history(messages: List[BaseMessage], max_messages: int) -> str:
        """把消息列表格式化为 'user: ...' / 'assistant: ...' 文本，裁剪到最近 N 条。"""
        lines = []
        for message in messages[-max_messages:]:
            if isinstance(message, HumanMessage):
                role = ChatRole.USER.value
            elif isinstance(message, AIMessage):
                role = ChatRole.ASSISTANT.value
            else:
                continue
            content = message.content if isinstance(message.content, str) else ""
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines)

    @staticmethod
    async def _load_fallback_history(
        session_id_hex: str | None,
        max_messages: int,
        history_budget: int,
        model_name: str,
    ) -> str:
        """checkpointer 无历史时回落业务表读最近 N 条消息并过输入预算裁剪。"""
        if not session_id_hex:
            return ""
        # 局部导入：避免 agent 层与 database 层在模块加载期的耦合
        from database.postgre_client import get_session
        from database.rag.chat import ChatMessageRepository

        try:
            session_id = uuid.UUID(session_id_hex)
        except ValueError:
            return ""
        async with get_session() as session:
            records = await ChatMessageRepository(session).list_recent(
                session_id, max_messages
            )
        lines = [
            f"{record.role}: {record.content}"
            for record in records
            if record.content
            and record.role in (ChatRole.USER.value, ChatRole.ASSISTANT.value)
        ]
        return ChatGraph._trim_text_lines_to_budget(lines, history_budget, model_name)

    @staticmethod
    def _safe_stream_writer():
        """安全获取 custom 流写入器；脱离图执行上下文（直接调用节点/单测）时返回 None。"""
        try:
            from langgraph.config import get_stream_writer

            return get_stream_writer()
        except RuntimeError:
            return None

    @staticmethod
    async def _astream_accumulate(
        model, msgs: List[BaseMessage]
    ) -> Tuple[AIMessage, dict]:
        """流式调用模型并累积完整响应。

        token 增量会被 langgraph 的 stream_mode="messages" 自动捕获外发
        （metadata.langgraph_node 为 respond）；工具轮次模型的 content 通常为空
        （纯 tool_calls），空增量不产生答案帧。
        """
        response: AIMessage | None = None
        async for chunk in model.astream(msgs):
            response = chunk if response is None else response + chunk
        if response is None:
            # 模型流式返回为空（上游异常/空响应等）：兜底为一条提示消息，
            # 保证调用方的 tool_calls 判定、_answer_text 与状态回写不因
            # response=None 触发 AttributeError 而整轮 FAILED
            logger.warning("[CHAT] 模型流式返回为空，使用兜底提示文本")
            response = AIMessage(content="模型未返回内容，请重试。")
        usage = getattr(response, "usage_metadata", None) or {}
        return response, usage

    @staticmethod
    def _merge_usage(total: dict, usage: dict) -> dict:
        """把单次模型调用的 usage 累加进汇总（缺失字段按 0 处理）。"""
        return {
            "input_tokens": total.get("input_tokens", 0)
            + (usage.get("input_tokens") or 0),
            "output_tokens": total.get("output_tokens", 0)
            + (usage.get("output_tokens") or 0),
            "total_tokens": total.get("total_tokens", 0)
            + (usage.get("total_tokens") or 0),
        }

    @staticmethod
    def _merge_doc_dedup(existing: List[dict], new: List[dict]) -> List[dict]:
        """跨工具调用合并候选并按 (knowledge_base_id, point_id) 去重，保留既有顺序。

        分层工具（如 chunk_read）的候选可能无 point_id，回落 chunk_id /
        document_id 作去重键；三者均缺的候选无去重键，按序保留不参与去重。
        """

        def _doc_key(doc: dict):
            ident = doc.get("point_id") or doc.get("chunk_id") or doc.get("document_id")
            if not ident:
                return None
            return (doc.get("knowledge_base_id"), ident)

        seen = {key for key in (_doc_key(doc) for doc in existing) if key is not None}
        merged = list(existing)
        for doc in new:
            key = _doc_key(doc)
            if key is None or key not in seen:
                if key is not None:
                    seen.add(key)
                merged.append(doc)
        return merged

    # ---------- 输入预算守卫 ----------
    @staticmethod
    def _input_budget() -> int:
        """输入预算 = context_window − 输出预留 − 安全边际（vLLM 按输入+max_tokens 校验）。"""
        context_window = CFG.chat.context_window
        return (
            context_window
            - CFG.chat_max_output_tokens
            - int(context_window * _INPUT_BUDGET_SAFETY_MARGIN)
        )

    @staticmethod
    def _trim_messages_to_budget(
        messages: List[BaseMessage], budget: int, model_name: str
    ) -> Tuple[List[BaseMessage], List[str]]:
        """从最旧丢弃历史消息直到估算 ≤ 预算；返回 (保留列表, 被删消息 id 列表)。

        预算 ≤ 0（固定开销已超限）时全部丢弃，系统提示与本轮问题仍由
        _ensure_within_budget 尽力兜底。
        """
        if budget <= 0:
            return [], [m.id for m in messages if getattr(m, "id", None)]
        costs = [_message_token_cost(model_name, m) for m in messages]
        acc = 0
        keep_count = 0
        for cost in reversed(costs):
            if acc + cost > budget:
                break
            acc += cost
            keep_count += 1
        kept = messages[-keep_count:] if keep_count else []
        removed_ids = [
            m.id
            for m in messages[: len(messages) - keep_count]
            if getattr(m, "id", None)
        ]
        if removed_ids:
            logger.warning(
                f"[CHAT] 输入预算裁剪：丢弃 {len(removed_ids)} 条历史消息"
                f"（预算 {budget} token）"
            )
        return kept, removed_ids

    @staticmethod
    def _trim_text_lines_to_budget(
        lines: List[str], budget: int, model_name: str
    ) -> str:
        """从最旧丢弃文本行直到估算 ≤ 预算（fallback 历史用，无消息 id 可删）。"""
        if budget <= 0 or not lines:
            return ""
        acc = 0
        kept: List[str] = []
        for line in reversed(lines):
            cost = count_tokens(model_name, line) + _LINE_FIXED_TOKENS
            if acc + cost > budget:
                break
            acc += cost
            kept.append(line)
        if len(kept) < len(lines):
            logger.warning(
                f"[CHAT] fallback 历史预算裁剪：{len(lines)} → {len(kept)} 行"
                f"（预算 {budget} token）"
            )
        return "\n".join(reversed(kept))

    @staticmethod
    def _ensure_within_budget(
        msgs: List[BaseMessage], budget: int, model_name: str
    ) -> None:
        """每次模型调用前兜底：超预算时从最早的工具结果开始截断（保留前缀）。

        仅剩系统提示与本轮问题仍超预算（配置异常）时告警并尽力发送。
        """
        for _ in range(50):  # 渐进截断上限，防御异常输入下的死循环
            if _messages_tokens_cached(model_name, msgs) <= budget:
                return
            trimmed = False
            for idx, msg in enumerate(msgs):
                if (
                    isinstance(msg, ToolMessage)
                    and isinstance(msg.content, str)
                    and msg.content
                ):
                    keep_chars = max(1, len(msg.content) // 2)
                    msgs[idx] = msg.model_copy(
                        update={"content": msg.content[:keep_chars]}
                    )
                    trimmed = True
                    break
            if not trimmed:
                logger.warning(
                    f"[CHAT] 输入仍超预算 {budget}（系统提示/问题本身超限，尽力发送）"
                )
                return

    # ---------- respond 节点组件 ----------
    def _build_toolset(self, state: ChatState) -> List:
        """装配本轮工具集（开关语义：关闭的工具对模型不可见）。"""
        tools = [knowledge_base_search]
        if ENV.wiki_enabled:
            tools.insert(0, kb_wiki_lookup)
        # 分层确定性工具（零在线 LLM）：关系查询 + 块读取，供多跳推理自主调用；
        # 关闭开关即回到原工具集（行为不变）
        if ENV.agent_tools_enabled:
            tools.extend([entity_relation_lookup, chunk_read])
        if state.get("use_web_search"):
            tools.append(web_search)
        return tools

    async def _prepare_messages(
        self, state: ChatState, config: RunnableConfig
    ) -> Tuple[List[BaseMessage], List[str], int, str]:
        """组装本轮 messages（系统提示 + 历史 + 问题）。

        返回 (msgs, remove_ids, budget, model_name)：历史按 token 预算从最旧裁剪，
        remove_ids 随节点返回同步进 checkpoint；checkpoint 无历史时回落业务表。
        """
        question = state["question"]
        model_name = CFG.chat.model_name
        kb_hint = ", ".join(state.get("kb_ids") or []) or "（未指定，检索返回空）"
        # 分层工具指引与工具集开关联动：关闭开关时提示词同步回退（行为不变）
        guidance = AGENT_TOOLS_GUIDANCE if ENV.agent_tools_enabled else ""
        # 输入预算：固定开销（系统提示模板 + 本轮问题）先扣除，余量为历史预算；
        # 系统提示与本轮问题永不裁剪（循环级兑底见 _ensure_within_budget）
        budget = self._input_budget()
        fixed_cost = count_tokens(
            model_name,
            AGENT_PROMPT.format(history="", knowledge_base_ids=kb_hint) + guidance,
        ) + count_tokens(model_name, question)
        history_budget = budget - fixed_cost
        remove_ids: List[str] = []
        # messages 末尾是本轮刚追加的 HumanMessage，历史取其之前的部分；
        # checkpoint 无历史（新会话 / TTL 已清理 / 存量会话）：回落业务表
        history_messages = state["messages"][:-1]
        if history_messages:
            kept, remove_ids = self._trim_messages_to_budget(
                history_messages, history_budget, model_name
            )
            history = self._format_history(kept, CFG.chat_history_max_messages)
        else:
            thread_id = (config.get("configurable") or {}).get("thread_id")
            history = await self._load_fallback_history(
                thread_id,
                CFG.chat_history_max_messages,
                history_budget,
                model_name,
            )
        msgs: List[BaseMessage] = [
            SystemMessage(
                content=AGENT_PROMPT.format(history=history, knowledge_base_ids=kb_hint)
                + guidance
            ),
            HumanMessage(content=question),
        ]
        return msgs, remove_ids, budget, model_name

    async def _execute_tool(
        self,
        tool_call: dict,
        tool_rounds: int,
        navigation_context: List[dict],
        writer,
        kb_ids: List[str] | None = None,
    ) -> Tuple[str, ToolOutcome, dict]:
        """分派执行单次工具调用；返回 (tool_call_id, outcome, 指标增量)。

        navigation_context 就地累积（导航上下文供后续检索）。
        分层工具（关系查询/块读取）无条件以本轮请求的 kb_ids 覆盖库范围，
        确保读取作用域不超出当前请求授权的知识库（含空集=无权限）。
        """
        name = tool_call.get("name", "")
        args = dict(tool_call.get("args") or {})
        impl = TOOL_IMPLS.get(name)
        if impl is None:
            logger.warning(f"[CHAT] respond 收到未知工具调用: {name}")
            return (
                tool_call["id"],
                ToolOutcome(
                    text=f"未知工具 {name}，请改用可用工具。", docs=[], metrics={}
                ),
                {},
            )
        if name == "knowledge_base_search" and navigation_context:
            # 导航保持结构化上下文：主题摘要/关键词不序列化进证据 query，
            # 避免置换用户的词汇/语义信号。
            args["navigation"] = list(navigation_context)
        if name in ("entity_relation_lookup", "chunk_read"):
            # 分层工具同口径强制以请求解析的库范围快照覆盖模型入参（含空集），
            # 防止幻觉/被检索内容注入的 kb id 越权读取；
            # chunk_read 对空作用域显式拒绝（impl 层空列表=无权限，非全库）。
            args["knowledge_base_ids"] = list(kb_ids or [])
            if name == "chunk_read" and not kb_ids:
                return (
                    tool_call["id"],
                    ToolOutcome(
                        text="块读取：当前请求无可用知识库范围，无法读取。",
                        docs=[],
                        metrics={"chunks": 0},
                    ),
                    {},
                )
        if name in ("knowledge_base_search", "kb_wiki_lookup"):
            # 检索类工具强制以请求解析出的库范围快照覆盖模型入参（含空集），
            # 防止幻觉/注入的 kb id 越权跨库检索。
            args["knowledge_base_ids"] = list(kb_ids or [])
        if args.get("top_k") is not None:
            # 收敛模型可传入的 top_k，防止异常取值放大重排负载
            try:
                args["top_k"] = max(1, min(int(args["top_k"]), 20))
            except (TypeError, ValueError):
                args.pop("top_k", None)
        if writer is not None:
            writer(
                {"type": "think", "text": f"正在检索知识库（第 {tool_rounds} 轮）..."}
            )
        # 单工具失败不炸整轮问答：转为错误 ToolMessage 让模型基于失败提示继续
        # （如检索后端抖动、模型给出意外参数名等），并保留 tool_call_id 协议合法性
        try:
            outcome = await impl(**args)
        except BadException as exc:
            logger.warning(f"[CHAT] 工具 {name} 业务失败: {exc}")
            outcome = ToolOutcome(
                text=f"工具 {name} 执行失败：{exc}", docs=[], metrics={}
            )
        except Exception:
            logger.exception(f"[CHAT] 工具 {name} 执行异常")
            outcome = ToolOutcome(
                text=f"工具 {name} 执行异常，请基于已有信息继续，或调整检索词后重试。",
                docs=[],
                metrics={},
            )
        delta = {
            "reflect_rounds": outcome.metrics.get("reflect_rounds", 0),
            "retrieved_count": outcome.metrics.get("retrieved_count", 0),
            "reranked_count": outcome.metrics.get("reranked_count", 0),
            "wiki_hits": outcome.metrics.get("wiki_hits", 0),
        }
        if outcome.navigation:
            navigation_context.extend(outcome.navigation)
        return tool_call["id"], outcome, delta

    def _append_tool_result(
        self,
        tool_call_id: str,
        outcome: ToolOutcome,
        all_docs: List[dict],
        msgs: List[BaseMessage],
    ) -> None:
        """工具结果按全局编号重建为 ToolMessage（与 sources.index 严格对应）。

        fresh 为本轮去重后新增候选（对照 all_docs 跨轮去重），编号从
        len(all_docs)+1 起；无新增候选（空检索/降级提示）时回落工具原始
        text，避免空消息。all_docs 就地累积。
        """
        if outcome.navigation_only:
            fresh: List[dict] = []
        else:
            merged = self._merge_doc_dedup(all_docs, outcome.docs)
            fresh = merged[len(all_docs) :]
            all_docs.extend(fresh)
        if fresh:
            start = len(all_docs) - len(fresh)
            content = "\n\n".join(
                f"[{start + idx}] {doc.get('text', '')}"
                for idx, doc in enumerate(fresh, start=1)
            )
        else:
            content = outcome.text
        msgs.append(ToolMessage(content=content, tool_call_id=tool_call_id))

    @staticmethod
    def _build_sources(all_docs: List[dict]) -> List[dict]:
        """候选 → 结构化来源（编号与 ToolMessage 角标一致）。"""
        return [
            {
                "index": idx,
                "text": doc.get("text", ""),
                "source": doc.get("source", ""),
                "score": doc.get("score"),
                "knowledge_base_id": doc.get("knowledge_base_id"),
                "chapter_title": doc.get("chapter_title"),
                "document_id": doc.get("document_id"),
                "chunk_id": doc.get("chunk_id"),
                "page_start": doc.get("page_start"),
                "page_end": doc.get("page_end"),
            }
            for idx, doc in enumerate(all_docs, start=1)
        ]

    # ---------- 节点 ----------
    async def respond_node(self, state: ChatState, config: RunnableConfig):
        """Agentic 回答节点：对话模型自主决定改写与检索，循环至无工具调用后生成答案。

        问题改写决策属于对话模型：系统提示注入对话历史（checkpointer 无历史
        时回落业务表，见 _load_fallback_history），模型自行判断当前问题是否
        依赖指代、需要时以改写后的独立查询调用检索工具。

        工具循环：bind_tools([knowledge_base_search, web_search?]) 后逐轮调用模型——
        模型返回 tool_calls 则按 TOOL_IMPLS 分派执行（混合检索/反思自纠错/重排序
        收敛在 agent.tools.rag_tools 内），结果作为 ToolMessage 回填并继续；
        无 tool_calls 则输出最终答案。循环上限复用 CFG.rag_reflect_round_cap，
        超限后以无工具模型强制收尾，避免无限调用。

        编号策略：所有工具调用返回的候选统一追加进 all_docs（跨轮去重），
        ToolMessage 内容按全局编号 [n] 重建——与 sources.index 严格对应，
        模型引用角标即来源索引。工具中间消息只存节点局部，不回写 state
        messages，保持 checkpointer 历史干净（仅追加最终 AIMessage）。
        输入预算守卫：历史按 token 预算从最旧裁剪，裁剪结果经 RemoveMessage
        同步进 checkpoint（消息窗口有界，业务表完整历史不受影响）；工具结果
        在每次模型调用前兜底截断；系统提示与本轮问题永不裁剪。
        检索进度经 stream_mode="custom"（get_stream_writer）外发 think 事件。
        """
        writer = self._safe_stream_writer()
        question = state["question"]
        msgs, remove_ids, budget, model_name = await self._prepare_messages(
            state, config
        )
        reasoning_effort = state.get("reasoning_effort")
        model = build_chat_model(reasoning_effort=reasoning_effort).bind_tools(
            self._build_toolset(state)
        )

        all_docs: List[dict] = []
        tool_rounds = 0
        counters = {
            "reflect_rounds": 0,
            "retrieved_count": 0,
            "reranked_count": 0,
            "wiki_hits": 0,
        }
        tool_call_names: List[str] = []
        navigation_context: List[dict] = []
        usage_total: dict = {}
        response: AIMessage | None = None
        while True:
            # 每次模型调用前兜底：工具结果超预算时截断（见 _ensure_within_budget）
            self._ensure_within_budget(msgs, budget, model_name)
            response, usage = await self._astream_accumulate(model, msgs)
            usage_total = self._merge_usage(usage_total, usage)
            if not getattr(response, "tool_calls", None):
                break
            if tool_rounds >= CFG.rag_reflect_round_cap:
                # 达到工具循环上限：带 tool_calls 的响应必须紧跟对应 role=tool
                # 消息（否则严格后端对悬空 tool_calls 的续写请求返回 400），
                # 先逐个回填占位 ToolMessage，再切无工具模型强制收尾
                msgs.append(response)
                for tool_call in response.tool_calls:
                    msgs.append(
                        ToolMessage(
                            content="已达到检索轮数上限，本次调用未执行。",
                            tool_call_id=tool_call["id"],
                        )
                    )
                msgs.append(
                    SystemMessage(
                        content="已达到检索轮数上限，请直接基于已有检索结果组织回答。"
                    )
                )
                self._ensure_within_budget(msgs, budget, model_name)
                response, usage = await self._astream_accumulate(
                    build_chat_model(reasoning_effort=reasoning_effort), msgs
                )
                usage_total = self._merge_usage(usage_total, usage)
                break
            tool_rounds += 1
            msgs.append(response)
            # 本轮全部工具调用执行完毕后统一分配全局编号（并行调用编号不冲突）
            for tool_call in response.tool_calls:
                tool_call_names.append(tool_call.get("name", ""))
                tool_call_id, outcome, delta = await self._execute_tool(
                    tool_call,
                    tool_rounds,
                    navigation_context,
                    writer,
                    kb_ids=state.get("kb_ids") or [],
                )
                for key, value in delta.items():
                    counters[key] += value
                self._append_tool_result(tool_call_id, outcome, all_docs, msgs)
            if writer is not None:
                writer(
                    {"type": "think", "text": f"已检索到 {len(all_docs)} 条相关内容..."}
                )

        metrics = {
            "tool_rounds": tool_rounds,
            **counters,
            # 真实重排结果数：各次检索工具调用 rerank 裁剪后的返回条数之和
            # （此前误用 len(all_docs)——那是跨轮去重后的累计候选数，与
            # 重排输出不是同一口径；sources 仍按 all_docs 构建，不受影响）
            "reranked_count": counters["reranked_count"],
            "tool_call_names": tool_call_names,
            **usage_total,
            "model": CFG.chat.model_name,
        }
        logger.info(
            f"[CHAT] 回答完成：tool_rounds={tool_rounds}, docs={len(all_docs)}, "
            f"tokens={usage_total.get('total_tokens', 0)}"
        )
        # 裁剪同步进 checkpoint：被预算裁掉的旧消息经 RemoveMessage 从
        # state messages 删除（业务表 chat_messages 完整历史不受影响）
        removals = [RemoveMessage(id=msg_id) for msg_id in remove_ids]
        return {
            "messages": [response, *removals],
            "answer": self._answer_text(response),
            "sources": self._build_sources(all_docs),
            "metrics": metrics,
        }

    @staticmethod
    def _answer_text(response: AIMessage) -> str:
        """答案文本归一化：content 恒为字符串。

        推理/多模态系模型可能返回内容块列表（text 块 + reasoning 等非文本块），
        仅拼接 text 块，避免 list 直落 state/SSE/持久层。
        """
        content = response.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        return str(content) if content else ""

    # ---------- 组装图 ----------
    def build(self, checkpointer):
        """构建并编译 chat 父图；checkpointer 由调用方（lifespan 装配层）传入。"""
        workflow = StateGraph(ChatState)

        workflow.add_node(ChatNode.RESPOND.value, self.respond_node)

        workflow.add_edge(START, ChatNode.RESPOND.value)
        workflow.add_edge(ChatNode.RESPOND.value, END)

        return workflow.compile(checkpointer=checkpointer)

    def get(self):
        """获取父图惰性单例：首次调用时取 lifespan 已装配的 checkpointer 编译。"""
        if self._compiled is None:
            from agent.checkpoints.postgres import get_checkpointer

            self._compiled = self.build(get_checkpointer())
        return self._compiled

    def reset(self) -> None:
        """重置编译单例（关停时由 lifespan 调用，避免持有已关闭池的引用）。"""
        self._compiled = None


# 模块级单例：服务层通过 chat_graph.get() 获取编译图，lifespan 关停时 chat_graph.reset()
chat_graph = ChatGraph()
