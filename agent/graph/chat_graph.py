"""
Chat 问答父图（LangGraph）—— 多轮编排 + 检索子图 + 流式生成。

职责划分（方案 C）：
- 父图负责多轮状态管理（checkpointer 恢复 messages 历史）、condense 问题改写、
  流式生成答案与结构化 sources；
- RAG 检索子图（agent.graph.sub.rag_graph）作为纯检索管线在 rag_retrieve 节点内
  显式状态映射后调用，子图不单独挂 checkpointer（持久化边界由父图统一）。

节点（全部 async）：
- condense：无历史时直通；有历史时用 rewrite/compression 模型把当前问题
  改写为指代清晰的独立问题；checkpointer 无历史（TTL 已清理/存量会话）时
  回落业务表 rag.chat_messages 读最近 N 条作为改写历史（业务表是事实源）；
- rag_retrieve：节点内 `await rag_graph.graph.ainvoke(...)`，输入 standalone 问题
  与 kb_ids，产出 reranked_docs；
- respond：基于 reranked_docs 与历史生成最终答案（该节点内的模型调用 token
  经 astream(stream_mode="messages") 外流），并构造结构化 sources。

入口：模块级单例 `chat_graph = ChatGraph()`，通过 `chat_graph.get()` 惰性编译
（依赖 lifespan 已装配的 checkpointer，模块 import 期不建连不编译）。
调用时 config 须携带 `{"configurable": {"thread_id": session_id_hex}}`；
每轮输入 state 为 `{messages: [HumanMessage(question)], question, kb_ids,
use_web_search, reasoning_effort}`。
终态含 `answer`（字符串）与 `sources`（每项
`{text, source, score, knowledge_base_id, chapter_title, document_id, chunk_id}`）。
"""

import uuid
from typing import List

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph

from agent.constants.enums.chat import ChatNode, ChatRole
from agent.prompts.chat import CONDENSE_PROMPT, RESPOND_PROMPT
from agent.graph.sub.rag_graph import rag_graph
from model.chat.factory import build_chat_model
from model.compression.factory import build_compression_model
from utils.env import ENV
from utils.logger import logger


class ChatState(MessagesState):
    """父图状态：messages 跨轮累积（checkpointer 持久化），其余字段每轮覆盖。"""

    # 本轮原始问题
    question: str
    # condense 改写后的独立问题（无历史时等于原始问题）
    standalone_question: str
    # 本轮检索范围（hex 无连字符列表，消息级，由调用方解析后传入）
    kb_ids: List[str]
    # 联网搜索开关（透传给检索子图，暂未实现）
    use_web_search: bool
    # 本轮思考强度（reasoning_effort，缺省用模块级默认模型）
    reasoning_effort: str | None
    # 检索子图产出的重排序候选
    reranked_docs: List[dict]
    # 推理复杂度指标（子图检索指标 + 父图 token/耗时/模型，服务层补齐耗时）
    metrics: dict
    # 最终答案与结构化来源
    answer: str
    sources: List[dict]


class ChatGraph:
    """Chat 父图封装：持有对话/改写模型与编译单例（get() 惰性编译）。"""

    def __init__(self):
        # 对话生成模型（respond 节点，token 流式外发）
        self.response_model = build_chat_model()
        # 问题改写模型（condense 节点，低温度贴近原意）
        self.condense_model = build_compression_model()
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

    # ---------- 节点 ----------
    async def condense_node(self, state: ChatState, config: RunnableConfig):
        """结合历史把当前问题改写为独立问题；无任何历史时直通原问题。"""
        question = state["question"]
        # messages 末尾是本轮刚追加的 HumanMessage，历史取其之前的部分
        history_messages = state["messages"][:-1]
        max_messages = ENV.chat_history_max_messages
        history = self._format_history(history_messages, max_messages)

        if not history:
            # checkpoint 无历史（新会话 / TTL 已清理 / 存量会话）：回落业务表
            thread_id = (config.get("configurable") or {}).get("thread_id")
            history = await self._load_fallback_history(thread_id, max_messages)

        if not history:
            # 首轮：无需改写，节约一次模型调用
            return {"standalone_question": question}

        prompt = CONDENSE_PROMPT.format(history=history, question=question)
        response = await self.condense_model.ainvoke(
            [{"role": ChatRole.USER.value, "content": prompt}]
        )
        standalone = (response.content or "").strip() or question
        return {"standalone_question": standalone}

    async def rag_retrieve_node(self, state: ChatState):
        """调用 RAG 检索子图（显式状态映射）：standalone 问题进，重排序候选出。

        两图 state schema 不同，走节点内调用而非 add_node(subgraph)；
        子图内部消息不回写父图 messages，避免检索中间消息污染对话历史。
        """
        standalone = state["standalone_question"]
        result = await rag_graph.graph.ainvoke(
            {
                "messages": [HumanMessage(content=standalone)],
                "question": standalone,
                "knowledge_base_ids": state.get("kb_ids") or [],
                "use_web_search": state.get("use_web_search", False),
            }
        )
        reranked = result.get("reranked_docs", [])
        metrics = result.get("metrics", {})
        logger.info(f"[CHAT] 检索子图完成：candidates={len(reranked)}")
        return {"reranked_docs": reranked, "metrics": metrics}

    async def respond_node(self, state: ChatState):
        """基于重排序候选与历史生成最终答案，并构造结构化 sources。

        本节点的模型调用 token 会被 astream(stream_mode='messages') 捕获外发；
        父图 messages 只追加最终 AIMessage（用户问题在进图输入中已追加）。
        """
        question = state["question"]
        docs = state.get("reranked_docs", [])
        history = self._format_history(
            state["messages"][:-1], ENV.chat_history_max_messages
        )
        # 为各候选标注 [n] 序号（与 sources.index 对应），引导答案引用角标
        context = "\n\n".join(
            f"[{idx}] {doc.get('text', '')}" for idx, doc in enumerate(docs, start=1)
        )

        prompt = RESPOND_PROMPT.format(
            history=history, question=question, context=context
        )
        # 携带思考强度时按请求构造本轮模型，否则沿用模块级默认模型
        reasoning_effort = state.get("reasoning_effort")
        model = (
            build_chat_model(reasoning_effort=reasoning_effort)
            if reasoning_effort
            else self.response_model
        )
        response = await model.ainvoke(
            [{"role": ChatRole.USER.value, "content": prompt}]
        )
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
            for idx, doc in enumerate(docs, start=1)
        ]
        # 汇入 respond 模型的 token 用量与模型名（usage 缺失时为 None）
        usage = getattr(response, "usage_metadata", None) or {}
        metrics = {
            **state.get("metrics", {}),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "model": ENV.chat_model_name,
        }
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

        workflow.add_node(ChatNode.CONDENSE.value, self.condense_node)
        workflow.add_node(ChatNode.RAG_RETRIEVE.value, self.rag_retrieve_node)
        workflow.add_node(ChatNode.RESPOND.value, self.respond_node)

        workflow.add_edge(START, ChatNode.CONDENSE.value)
        workflow.add_edge(ChatNode.CONDENSE.value, ChatNode.RAG_RETRIEVE.value)
        workflow.add_edge(ChatNode.RAG_RETRIEVE.value, ChatNode.RESPOND.value)
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
