"""
Agentic RAG 图（LangGraph）。

复用 LangChain agentic-rag 教程结构，检索层替换为项目的 Qdrant retriever tool
（agent.tools.document.retrieve_documents），chat 模型走 vLLM OpenAI 兼容接口。

节点：
- generate_query_or_respond：LLM 决定直接回答，还是调用 retriever tool；
- retrieve：ToolNode，执行检索；
- grade_documents：条件边，判断检索内容是否相关（相关→生成答案，不相关→改写问题）；
- rewrite_question：改写原始问题后重试；
- generate_answer：基于检索上下文生成最终答案。

入口：模块级 `graph`（已 compile），可直接 graph.invoke(...) / graph.stream(...)。
"""

from typing import Literal

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from agent.prompts.rag import GENERATE_PROMPT, GRADE_PROMPT, REWRITE_PROMPT
from agent.tools.document import retrieve_documents
from model.chat.factory import build_chat_model

response_model = build_chat_model()
grader_model = build_chat_model()


class GradeDocuments(BaseModel):
    """用二值分数标记检索文档是否相关。"""

    binary_score: str = Field(
        description="Relevance score: 'yes' if relevant, or 'no' if not relevant"
    )


# ---------- 节点 ----------
def generate_query_or_respond(state: MessagesState):
    """LLM 根据当前对话决定：调用 retriever tool 检索，或直接回答用户。"""
    response = response_model.bind_tools([retrieve_documents]).invoke(state["messages"])
    return {"messages": [response]}


def grade_documents(
    state: MessagesState,
) -> Literal["generate_answer", "rewrite_question"]:
    """判断检索到的文档是否与问题相关，决定下一步走向。"""
    question = state["messages"][0].content
    context = state["messages"][-1].content

    prompt = GRADE_PROMPT.format(question=question, context=context)
    response = grader_model.with_structured_output(GradeDocuments).invoke(
        [{"role": "user", "content": prompt}]
    )
    if response.binary_score == "yes":
        return "generate_answer"
    return "rewrite_question"


def rewrite_question(state: MessagesState):
    """检索结果不相关时，改写原始问题后重试。"""
    question = state["messages"][0].content
    prompt = REWRITE_PROMPT.format(question=question)
    response = response_model.invoke([{"role": "user", "content": prompt}])
    return {"messages": [HumanMessage(content=response.content)]}


def generate_answer(state: MessagesState):
    """基于原始问题与检索上下文生成最终答案。"""
    question = state["messages"][0].content
    context = state["messages"][-1].content
    prompt = GENERATE_PROMPT.format(question=question, context=context)
    response = response_model.invoke([{"role": "user", "content": prompt}])
    return {"messages": [response]}


def route_on_tool_calls(state: MessagesState):
    """根据模型是否发起 tool call 决定去检索还是结束。"""
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    return END


# ---------- 组装图 ----------
def build_graph():
    workflow = StateGraph(MessagesState)

    workflow.add_node(generate_query_or_respond)
    workflow.add_node("retrieve", ToolNode([retrieve_documents]))
    workflow.add_node(rewrite_question)
    workflow.add_node(generate_answer)

    workflow.add_edge(START, "generate_query_or_respond")
    workflow.add_conditional_edges(
        "generate_query_or_respond",
        route_on_tool_calls,
        {"tools": "retrieve", END: END},
    )
    workflow.add_conditional_edges("retrieve", grade_documents)
    workflow.add_edge("generate_answer", END)
    workflow.add_edge("rewrite_question", "generate_query_or_respond")

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
    result["messages"][-1].pretty_print()
