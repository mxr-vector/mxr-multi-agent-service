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

import uuid
from typing import List, Tuple

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph

from agent.constants.enums.chat import ChatNode, ChatRole
from agent.prompts.chat import AGENT_PROMPT
from agent.tools.rag_tools import (
    TOOL_IMPLS,
    TOOL_KNOWLEDGE_BASE_SEARCH,
    TOOL_WEB_SEARCH,
    ToolOutcome,
)
from model.chat.factory import build_chat_model
from core.config_snapshot import CFG
from utils.logger import logger


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
        session_id_hex: str | None, max_messages: int
    ) -> str:
        """checkpointer 无历史时回落业务表读最近 N 条消息（业务表是事实源）。"""
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
        return "\n".join(lines)

    @staticmethod
    def _safe_stream_writer():
        """安全获取 custom 流写入器；脱离图执行上下文（直接调用节点/单测）时返回 None。"""
        try:
            from langgraph.config import get_stream_writer

            return get_stream_writer()
        except RuntimeError:
            return None

    @staticmethod
    async def _astream_accumulate(model, msgs: List[BaseMessage]) -> Tuple[AIMessage, dict]:
        """流式调用模型并累积完整响应。

        token 增量会被 langgraph 的 stream_mode="messages" 自动捕获外发
        （metadata.langgraph_node 为 respond）；工具轮次模型的 content 通常为空
        （纯 tool_calls），空增量不产生答案帧。
        """
        response: AIMessage | None = None
        async for chunk in model.astream(msgs):
            response = chunk if response is None else response + chunk
        usage = getattr(response, "usage_metadata", None) or {}
        return response, usage

    @staticmethod
    def _merge_usage(total: dict, usage: dict) -> dict:
        """把单次模型调用的 usage 累加进汇总（缺失字段按 0 处理）。"""
        return {
            "input_tokens": total.get("input_tokens", 0) + (usage.get("input_tokens") or 0),
            "output_tokens": total.get("output_tokens", 0) + (usage.get("output_tokens") or 0),
            "total_tokens": total.get("total_tokens", 0) + (usage.get("total_tokens") or 0),
        }

    @staticmethod
    def _merge_doc_dedup(existing: List[dict], new: List[dict]) -> List[dict]:
        """跨工具调用合并候选并按 (knowledge_base_id, point_id) 去重，保留既有顺序。"""
        seen = {(doc.get("knowledge_base_id"), doc["point_id"]) for doc in existing}
        merged = list(existing)
        for doc in new:
            key = (doc.get("knowledge_base_id"), doc["point_id"])
            if key not in seen:
                seen.add(key)
                merged.append(doc)
        return merged

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
        检索进度经 stream_mode="custom"（get_stream_writer）外发 think 事件。
        """
        writer = self._safe_stream_writer()
        question = state["question"]
        # messages 末尾是本轮刚追加的 HumanMessage，历史取其之前的部分；
        # checkpoint 无历史（新会话 / TTL 已清理 / 存量会话）：回落业务表
        history_messages = state["messages"][:-1]
        history = self._format_history(
            history_messages, CFG.chat_history_max_messages
        )
        if not history:
            thread_id = (config.get("configurable") or {}).get("thread_id")
            history = await self._load_fallback_history(
                thread_id, CFG.chat_history_max_messages
            )
        kb_hint = ", ".join(state.get("kb_ids") or []) or "（未指定，检索返回空）"
        msgs: List[BaseMessage] = [
            SystemMessage(
                content=AGENT_PROMPT.format(history=history, knowledge_base_ids=kb_hint)
            ),
            HumanMessage(content=question),
        ]
        # use_web_search=False 时不绑定 web_search 工具（模型不可见，开关语义保留）
        tools = [TOOL_KNOWLEDGE_BASE_SEARCH]
        if state.get("use_web_search"):
            tools.append(TOOL_WEB_SEARCH)
        reasoning_effort = state.get("reasoning_effort")
        model = build_chat_model(reasoning_effort=reasoning_effort).bind_tools(tools)

        all_docs: List[dict] = []
        tool_rounds = 0
        reflect_rounds = 0
        retrieved_count = 0
        usage_total: dict = {}
        response: AIMessage | None = None
        while True:
            response, usage = await self._astream_accumulate(model, msgs)
            usage_total = self._merge_usage(usage_total, usage)
            if not getattr(response, "tool_calls", None):
                break
            if tool_rounds >= CFG.rag_reflect_round_cap:
                # 达到工具循环上限：切无工具模型强制收尾
                msgs.append(
                    SystemMessage(
                        content="已达到检索轮数上限，请直接基于已有检索结果组织回答。"
                    )
                )
                response, usage = await self._astream_accumulate(
                    build_chat_model(reasoning_effort=reasoning_effort), msgs
                )
                usage_total = self._merge_usage(usage_total, usage)
                break
            tool_rounds += 1
            msgs.append(response)
            # 本轮全部工具调用执行完毕后统一分配全局编号（并行调用编号不冲突）
            outcomes: List[Tuple[str, ToolOutcome]] = []
            for tool_call in response.tool_calls:
                name = tool_call.get("name", "")
                args = tool_call.get("args") or {}
                impl = TOOL_IMPLS.get(name)
                if impl is None:
                    logger.warning(f"[CHAT] respond 收到未知工具调用: {name}")
                    outcomes.append(
                        (
                            tool_call["id"],
                            ToolOutcome(
                                text=f"未知工具 {name}，请改用可用工具。",
                                docs=[],
                                metrics={},
                            ),
                        )
                    )
                    continue
                if writer is not None:
                    writer({"type": "think", "text": f"正在检索知识库（第 {tool_rounds} 轮）..."})
                outcome = await impl(**args)
                reflect_rounds += outcome.metrics.get("reflect_rounds", 0)
                retrieved_count += outcome.metrics.get("retrieved_count", 0)
                outcomes.append((tool_call["id"], outcome))
            for tool_call_id, outcome in outcomes:
                # 全局编号重建工具结果文本（fresh 为去重后新增候选，编号从 len(all_docs)+1 起）；
                # 无新增候选（空检索/未实现降级提示）时回落工具的原始 text，避免空消息
                fresh = self._merge_doc_dedup([], outcome.docs)
                all_docs = self._merge_doc_dedup(all_docs, fresh)
                if fresh:
                    start = len(all_docs) - len(fresh)
                    content = "\n\n".join(
                        f"[{start + idx}] {doc.get('text', '')}"
                        for idx, doc in enumerate(fresh, start=1)
                    )
                else:
                    content = outcome.text
                msgs.append(ToolMessage(content=content, tool_call_id=tool_call_id))
            if writer is not None:
                writer({"type": "think", "text": f"已检索到 {len(all_docs)} 条相关内容..."})

        sources = [
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
        metrics = {
            "tool_rounds": tool_rounds,
            "reflect_rounds": reflect_rounds,
            "retrieved_count": retrieved_count,
            "reranked_count": len(all_docs),
            **usage_total,
            "model": CFG.chat.model_name,
        }
        logger.info(
            f"[CHAT] 回答完成：tool_rounds={tool_rounds}, docs={len(all_docs)}, "
            f"tokens={usage_total.get('total_tokens', 0)}"
        )
        return {
            "messages": [response],
            "answer": response.content,
            "sources": sources,
            "metrics": metrics,
        }

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
