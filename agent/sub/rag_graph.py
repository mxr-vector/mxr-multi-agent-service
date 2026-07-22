"""
Agentic RAG 图（LangGraph）—— 混合召回 + 反思 + 重排序架构。

检索层使用项目的 Qdrant 混合检索（dense 语义 + sparse BM25 关键词，服务端 RRF 融合、
point id 去重，见 agent.tools.document.hybrid_retrieve），chat 模型走 vLLM OpenAI 兼容接口。

节点：
- retrieve：混合召回并把去重候选合并进 `retrieved_docs` 结构化状态，同时追加一条上下文消息；
- reflect：LLM 判断累积上下文是否足以回答；充分或达到轮数上限则进入重排序，
  否则扩展查询并回到检索（轮数上限 ENV.rag_reflect_round_cap）；
- rerank：反思循环结束后运行一次，用 rerank client 对去重候选打分并裁剪到 top-k；
- generate_answer：基于重排序后的候选生成答案，并返回结构化 `{answer, sources[]}`。

入口：模块级 `graph`（已 compile），可直接 graph.invoke(...) / graph.stream(...)。
最终状态含 `answer`（字符串）与 `sources`（每项 `{text, source, score}`）。
"""

from typing import List

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import BaseModel, Field

from agent.constants.enums.rag import GradeScore, MessageRole, RagNode
from agent.prompts.rag import GENERATE_PROMPT, REFLECT_PROMPT, REWRITE_PROMPT
from agent.tools.document import hybrid_retrieve
from model.chat.factory import build_chat_model
from model.compression.factory import build_compression_model
from model.rerank.factory import get_rerank_client
from utils.env import ENV

# 对话生成模型
response_model = build_chat_model()
# LLM 二值仲裁评分模型（用于反思判断上下文是否充分）
grader_model = build_chat_model()
# 改写/扩展类辅助任务使用独立模型，与对话模型各司其职。
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
    # 当前用于检索的查询（反思扩展后更新）
    current_query: str
    # 混合召回并按 point id 去重后的候选：{point_id, text, source, score}
    retrieved_docs: List[dict]
    # 已运行的检索轮数（用于限制反思循环）
    reflect_round: int
    # 反思判定：上下文是否充分（或达到轮数上限，可进入重排序）
    reflect_sufficient: bool
    # 重排序并裁剪到 top-k 后的候选
    reranked_docs: List[dict]
    # 最终答案与结构化来源
    answer: str
    sources: List[dict]


# ---------- 辅助 ----------
def _merge_dedup(existing: List[dict], new: List[dict]) -> List[dict]:
    """按 point_id 合并去重，保留既有顺序并追加新增候选。"""
    seen = {doc["point_id"] for doc in existing}
    merged = list(existing)
    for doc in new:
        if doc["point_id"] not in seen:
            seen.add(doc["point_id"])
            merged.append(doc)
    return merged


def _join_context(docs: List[dict]) -> str:
    """把候选文本拼接为供 LLM 阅读的上下文。"""
    return "\n\n".join(doc.get("text", "") for doc in docs)


# ---------- 节点 ----------
def retrieve_node(state: RagState):
    """混合召回：dense + sparse + 服务端 RRF，去重后合并进状态并追加上下文消息。"""
    question = state.get("question") or state["messages"][0].content
    query = state.get("current_query") or question

    new_docs = hybrid_retrieve(query)
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


def reflect_node(state: RagState):
    """判断累积上下文是否充分：充分或达轮数上限则进入重排序，否则扩展查询继续检索。"""
    question = state["question"]
    context = _join_context(state.get("retrieved_docs", []))
    round_no = state.get("reflect_round", 0)

    prompt = REFLECT_PROMPT.format(question=question, context=context)
    verdict = grader_model.with_structured_output(SufficiencyGrade).invoke(
        [{"role": MessageRole.USER.value, "content": prompt}]
    )
    sufficient = verdict.binary_score == GradeScore.YES.value

    # 上下文充分，或已达到最大检索轮数上限，进入重排序。
    if sufficient or round_no >= ENV.rag_reflect_round_cap:
        return {"reflect_sufficient": True}

    # 上下文不足且仍在轮数内：扩展/改写查询后回到检索（轮数由 retrieve_node 累加）。
    response = rewrite_model.invoke(
        [
            {
                "role": MessageRole.USER.value,
                "content": REWRITE_PROMPT.format(question=question),
            }
        ]
    )
    return {"reflect_sufficient": False, "current_query": response.content}


def rerank_node(state: RagState):
    """反思循环结束后运行一次：对去重候选打分并裁剪到 top-k（按相关性排序）。"""
    docs = state.get("retrieved_docs", [])
    if not docs:
        return {"reranked_docs": []}

    results = get_rerank_client().rerank(
        state["question"],
        [doc.get("text", "") for doc in docs],
        top_n=ENV.rag_final_top_k,
    )
    reranked = [{**docs[result.index], "score": result.score} for result in results]
    return {"reranked_docs": reranked}


def generate_answer(state: RagState):
    """基于重排序后的候选生成最终答案，并返回结构化 {answer, sources[]}。"""
    question = state["question"]
    docs = state.get("reranked_docs", [])
    context = _join_context(docs)

    prompt = GENERATE_PROMPT.format(question=question, context=context)
    response = response_model.invoke(
        [{"role": MessageRole.USER.value, "content": prompt}]
    )
    sources = [
        {
            "text": doc.get("text", ""),
            "source": doc.get("source", ""),
            "score": doc.get("score"),
        }
        for doc in docs
    ]
    return {"messages": [response], "answer": response.content, "sources": sources}


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
    workflow.add_node(RagNode.GENERATE_ANSWER.value, generate_answer)

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
    workflow.add_edge(RagNode.RERANK.value, RagNode.GENERATE_ANSWER.value)
    workflow.add_edge(RagNode.GENERATE_ANSWER.value, END)

    return workflow.compile()


graph = build_graph()


if __name__ == "__main__":
    result = graph.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "What does Lilian Weng say about types of reward hacking?",
                }
            ]
        }
    )
    print("answer:", result["answer"])
    for source in result["sources"]:
        print(source)
