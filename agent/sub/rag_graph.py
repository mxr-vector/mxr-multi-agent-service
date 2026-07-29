"""
Agentic RAG 检索子图（LangGraph）—— 混合召回 + 反思 + 重排序。

本图为纯检索管线，作为 chat 父图（agent.sub.chat_graph）的子图在节点内调用：
不生成答案、不调用对话生成模型，终态输出为重排序候选 `reranked_docs`
（每项保留完整溯源字段），答案生成与 sources 对外暴露由父图 respond 节点负责。

检索层使用项目的 Qdrant 混合检索（dense 语义 + sparse BM25 关键词，服务端 RRF 融合、
point id 去重，见 agent.tools.document.hybrid_retrieve）。

节点（全部 async，同步 IO 经 asyncio.to_thread 包装）：
- retrieve：混合召回并把去重候选合并进 `retrieved_docs` 结构化状态；
- reflect：LLM 判断累积上下文是否足以回答；充分或达到轮数上限则进入重排序，
  否则扩展查询并回到检索（轮数上限 ENV.rag_reflect_round_cap）；
- rerank：反思循环结束后运行一次，用 rerank client 对去重候选打分并裁剪到 top-k。

入口：模块级 `graph`（已 compile，无 checkpointer——由父图传播持久化边界）。
初始 state 须携带 `question` 与 `knowledge_base_ids`（hex 无连字符列表）：
前端选库时为所选知识库；未选库时由调用方在进图前解析为当前用户的
缺省可见范围（见 service.rag.knowledge_base.KnowledgeBaseService.list_visible_ids），
跨多个 Qdrant 集合扇出检索。联网搜索由 `use_web_search` 方法级开关显式控制
（暂未实现），与知识库选择解耦。
最终状态含 `reranked_docs`（每项
`{point_id, knowledge_base_id, text, source, score, chapter_title, document_id, chunk_id}`）。
"""

import asyncio
import uuid
from typing import List

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import BaseModel, Field

from agent.constants.enums.rag import GradeScore, MessageRole, RagNode
from agent.prompts.rag import REFLECT_PROMPT, REWRITE_PROMPT
from agent.tools.document import hybrid_retrieve_multi, web_search_retrieve
from model.compression.factory import build_compression_model
from model.rerank.factory import get_rerank_client
from utils.env import ENV

# LLM 二值仲裁评分模型（用于反思判断上下文是否充分）——判断/改写类辅助任务
# 统一走 rewrite/compression 模型，本子图不引用对话生成模型（答案生成在父图）。
grader_model = build_compression_model()
# 改写/扩展类辅助任务模型
rewrite_model = build_compression_model()


class SufficiencyGrade(BaseModel):
    """用二值分数标记累积检索上下文是否足以回答问题。"""

    binary_score: str = Field(
        description=(
            f"Sufficiency score: '{GradeScore.YES.value}' if the context is "
            f"sufficient to answer, or '{GradeScore.NO.value}' if more retrieval is needed"
        )
    )


class RagState(MessagesState):
    """在消息状态基础上追加结构化检索候选与反思轮数计数。"""

    # 原始问题（首轮从首条消息提取后固定）
    question: str
    # 目标知识库 id 列表（hex 无连字符）；未选库时由调用方预先解析为
    # 当前用户缺省可见范围（本人库 ∪ 本人部门 department 库 ∪ public 库），空列表检索结果为空
    knowledge_base_ids: List[str]
    # 联网搜索开关（方法级变量，与知识库选择解耦；暂未实现）
    use_web_search: bool
    # 当前用于检索的查询（反思扩展后更新）
    current_query: str
    # 混合召回并按 point id 去重后的候选：{point_id, text, source, score}
    retrieved_docs: List[dict]
    # 已运行的检索轮数（用于限制反思循环）
    reflect_round: int
    # 反思判定：上下文是否充分（或达到轮数上限，可进入重排序）
    reflect_sufficient: bool
    # 重排序并裁剪到 top-k 后的候选（本子图的终态输出）
    reranked_docs: List[dict]
    # 检索复杂度指标（供上层汇总）：{reflect_rounds, retrieved_count, reranked_count}
    metrics: dict


# ---------- 辅助 ----------
def _dedup_key(doc: dict) -> tuple:
    """跨库去重键：point id 在集合内唯一，跨集合需叠加知识库 id 复合判定。"""
    return (doc.get("knowledge_base_id"), doc["point_id"])


def _merge_dedup(existing: List[dict], new: List[dict]) -> List[dict]:
    """按 (knowledge_base_id, point_id) 合并去重，保留既有顺序并追加新增候选。"""
    seen = {_dedup_key(doc) for doc in existing}
    merged = list(existing)
    for doc in new:
        if _dedup_key(doc) not in seen:
            seen.add(_dedup_key(doc))
            merged.append(doc)
    return merged


def _join_context(docs: List[dict]) -> str:
    """把候选文本拼接为供 LLM 阅读的上下文。"""
    return "\n\n".join(doc.get("text", "") for doc in docs)


# ---------- 节点 ----------
async def retrieve_node(state: RagState):
    """混合召回：dense + sparse + 服务端 RRF，跨库扇出去重后合并进状态并追加上下文消息。

    检索链路为同步 IO（Qdrant/embedding，内部自带线程池扇出），
    经 asyncio.to_thread 包装避免阻塞事件循环。
    """
    question = state.get("question") or state["messages"][0].content
    query = state.get("current_query") or question

    if state.get("use_web_search"):
        # 联网搜索由方法级开关显式触发，与知识库选择解耦（暂未实现）
        new_docs = await asyncio.to_thread(web_search_retrieve, query)
    else:
        # 知识库 id 列表来自初始 state（hex 字符串），每轮检索都命中同一批知识库；
        # 未选库时由调用方预先解析为缺省可见范围，空列表召回为空
        kb_ids = [uuid.UUID(kb_hex) for kb_hex in state.get("knowledge_base_ids") or []]
        new_docs = await asyncio.to_thread(hybrid_retrieve_multi, query, kb_ids)

    merged = _merge_dedup(state.get("retrieved_docs", []), new_docs)
    round_no = state.get("reflect_round", 0) + 1

    return {
        "question": question,
        "current_query": query,
        "retrieved_docs": merged,
        "reflect_round": round_no,
        "messages": [
            HumanMessage(content=f"Retrieved context:\n\n{_join_context(new_docs)}")
        ],
    }


async def reflect_node(state: RagState):
    """判断累积上下文是否充分：充分或达轮数上限则进入重排序，否则扩展查询继续检索。"""
    question = state["question"]
    docs = state.get("retrieved_docs", [])
    round_no = state.get("reflect_round", 0)

    # 无任何候选（可见库为空/全部检索失败）：反思无意义，直接进入重排序收尾
    if not docs:
        return {"reflect_sufficient": True}

    context = _join_context(docs)
    prompt = REFLECT_PROMPT.format(question=question, context=context)
    # 结构化输出显式走 function_calling：json_schema 形态的 response_format
    # 在 vLLM / DeepSeek 等 OpenAI 兼容端普遍不可用，而工具调用兼容性最广
    verdict = await grader_model.with_structured_output(
        SufficiencyGrade, method="function_calling"
    ).ainvoke([{"role": MessageRole.USER.value, "content": prompt}])
    sufficient = verdict.binary_score == GradeScore.YES.value

    # 上下文充分，或已达到最大检索轮数上限，进入重排序。
    if sufficient or round_no >= ENV.rag_reflect_round_cap:
        return {"reflect_sufficient": True}

    # 上下文不足且仍在轮数内：扩展/改写查询后回到检索（轮数由 retrieve_node 累加）。
    response = await rewrite_model.ainvoke(
        [
            {
                "role": MessageRole.USER.value,
                "content": REWRITE_PROMPT.format(question=question),
            }
        ]
    )
    return {"reflect_sufficient": False, "current_query": response.content}


async def rerank_node(state: RagState):
    """反思循环结束后运行一次：对去重候选打分并裁剪到 top-k（按相关性排序）。

    rerank client 为同步 HTTP 调用，经 asyncio.to_thread 包装；
    终态同时产出检索复杂度 metrics（轮数/候选量/重排后候选量）。
    """
    docs = state.get("retrieved_docs", [])
    round_no = state.get("reflect_round", 0)
    if not docs:
        return {
            "reranked_docs": [],
            "metrics": {
                "reflect_rounds": round_no,
                "retrieved_count": 0,
                "reranked_count": 0,
            },
        }

    results = await asyncio.to_thread(
        get_rerank_client().rerank,
        state["question"],
        [doc.get("text", "") for doc in docs],
        top_n=ENV.rag_final_top_k,
    )
    reranked = [{**docs[result.index], "score": result.score} for result in results]
    return {
        "reranked_docs": reranked,
        "metrics": {
            "reflect_rounds": round_no,
            "retrieved_count": len(docs),
            "reranked_count": len(reranked),
        },
    }


def route_after_reflect(state: RagState) -> str:
    """反思后路由：充分则重排序，否则回到检索继续下一轮。"""
    if state.get("reflect_sufficient"):
        return RagNode.RERANK.value
    return RagNode.RETRIEVE.value


# ---------- 组装图 ----------
def build_graph():
    workflow = StateGraph(RagState)

    workflow.add_node(RagNode.RETRIEVE.value, retrieve_node)
    workflow.add_node(RagNode.REFLECT.value, reflect_node)
    workflow.add_node(RagNode.RERANK.value, rerank_node)

    workflow.add_edge(START, RagNode.RETRIEVE.value)
    workflow.add_edge(RagNode.RETRIEVE.value, RagNode.REFLECT.value)
    workflow.add_conditional_edges(
        RagNode.REFLECT.value,
        route_after_reflect,
        {
            RagNode.RERANK.value: RagNode.RERANK.value,
            RagNode.RETRIEVE.value: RagNode.RETRIEVE.value,
        },
    )
    workflow.add_edge(RagNode.RERANK.value, END)

    return workflow.compile()


graph = build_graph()


if __name__ == "__main__":
    # 手动冒烟需在初始 state 传入 hex 格式的 knowledge_base_ids 列表（可跨多个知识库）；
    # use_web_search=True 时走联网搜索通道，当前未实现，会抛 NotImplementedError。
    async def _smoke():
        result = await graph.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "What does Lilian Weng say about types of reward hacking?",
                    }
                ],
                "question": "What does Lilian Weng say about types of reward hacking?",
                "knowledge_base_ids": ["019fa739864b7d9297a65fb8058dbaa1"],
            }
        )
        for doc in result["reranked_docs"]:
            print(doc)

    asyncio.run(_smoke())
