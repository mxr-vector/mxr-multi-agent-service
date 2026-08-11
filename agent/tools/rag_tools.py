"""
Agentic RAG 检索工具（对话模型自主调用的工具实现）。

将原 RAG 检索子图（agent.graph.sub.rag_graph）的混合召回 + 反思 + 重排序
收敛为 knowledge_base_search 工具：对话模型在 chat 父图 respond 节点内通过
tool calling 自主决定何时检索、检索几次（见 agent.graph.chat_graph）。
联网搜索由 web_search 工具承载（暂未实现，注册占位）。

设计要点：
- 工具实现函数（*_impl）返回 ToolOutcome{text, docs, metrics}：text 为供 LLM
  阅读的候选文本；docs 为结构化候选（完整溯源字段），供父图构建 sources 与
  汇总 metrics；@tool 包装只暴露 text，供 bind_tools 生成 tool schema；
- 反思自纠错保留在工具内部：混合召回后由 rewrite/compression 模型判断
  累积上下文是否充分（REFLECT_PROMPT），不充分且未达轮数上限时改写查询
  再检索一轮（REWRITE_PROMPT），上限 CFG.rag_reflect_round_cap；
- 重排序：反思循环结束后用 rerank client 对去重候选打分并裁剪到
  CFG.rag_final_top_k（top_k 入参可覆盖）；
- 跨库检索复用 agent.tools.document.hybrid_retrieve_multi（服务端 RRF 融合、
  point id 去重、扇出失败单库跳过），候选溯源字段与文档管线一致；
- 同步 IO（Qdrant/embedding/rerank）经 asyncio.to_thread 包装；
- 冒烟测试：uv run python agent/tools/rag_tools.py（需先加载配置快照）。
"""

import asyncio
import uuid
from dataclasses import dataclass
from typing import List, Literal, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent.constants.enums.rag import GradeScore, MessageRole
from agent.prompts.rag import REFLECT_PROMPT, REWRITE_PROMPT
from agent.tools.document import hybrid_retrieve_multi
from core.config_snapshot import CFG
from model.compression.factory import build_compression_model
from model.rerank.factory import get_rerank_client
from utils.logger import logger

# 工具名常量：respond 节点经 TOOL_IMPLS 按此分派，bind_tools 亦按此构造
TOOL_KNOWLEDGE_BASE_SEARCH = "knowledge_base_search"
TOOL_WEB_SEARCH = "web_search"


class SufficiencyGrade(BaseModel):
    """用二值分数标记累积检索上下文是否足以回答问题。"""

    # Literal 枚举约束：在 tool schema 中转为 enum，强制模型只能输出 yes/no，
    # 避免小模型在自由字符串字段里填入多余内容导致判定失效
    binary_score: Literal["yes", "no"] = Field(
        description=(
            f"Sufficiency score: '{GradeScore.YES.value}' if the context is "
            f"sufficient to answer, or '{GradeScore.NO.value}' if more retrieval is needed"
        )
    )


@dataclass
class ToolOutcome:
    """工具执行结果：text 供 LLM 阅读，docs 供父图构建 sources 与汇总 metrics。"""

    text: str
    docs: List[dict]
    metrics: dict


# ---------- 候选处理（自 rag_graph 迁移） ----------
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
    """把候选文本拼接为供 LLM 阅读的上下文（不加编号，编号由父图统一分配）。"""
    return "\n\n".join(doc.get("text", "") for doc in docs)


# ---------- 反思自纠错（自 rag_graph reflect/rewrite 节点迁移） ----------
async def _context_sufficient(question: str, context: str) -> bool:
    """判断累积检索上下文是否足以回答问题（结构化输出走 function_calling）。"""
    prompt = REFLECT_PROMPT.format(question=question, context=context)
    verdict = (
        await build_compression_model()
        .with_structured_output(SufficiencyGrade, method="function_calling")
        .ainvoke([{"role": MessageRole.USER.value, "content": prompt}])
    )
    return verdict.binary_score == GradeScore.YES.value


async def _rewrite_query(question: str) -> str:
    """把原问题改写/扩展为检索效果更好的查询。"""
    response = await build_compression_model().ainvoke(
        [
            {
                "role": MessageRole.USER.value,
                "content": REWRITE_PROMPT.format(question=question),
            }
        ]
    )
    return response.content


async def _rerank(query: str, docs: List[dict], top_n: int) -> List[dict]:
    """对去重候选打分并裁剪到 top-n（按相关性排序）。"""
    results = await asyncio.to_thread(
        get_rerank_client().rerank,
        query,
        [doc.get("text", "") for doc in docs],
        top_n=top_n,
    )
    return [{**docs[result.index], "score": result.score} for result in results]


# ---------- 工具实现（返回结构化结果，供父图/评测脚本直接调用） ----------
async def knowledge_base_search_impl(
    query: str,
    knowledge_base_ids: List[str],
    top_k: Optional[int] = None,
) -> ToolOutcome:
    """知识库混合检索：混合召回 + 反思自纠错（改写重检）+ 重排序。

    - knowledge_base_ids 为 hex 无连字符列表（非法 id 跳过，空列表返回
      提示文本与空候选，供模型降级回答）；
    - 反思轮数上限 CFG.rag_reflect_round_cap，重排 top-n 取 CFG.rag_final_top_k
      （top_k 入参可覆盖）；
    - metrics 与原子图口径一致：{reflect_rounds, retrieved_count, reranked_count}。
    """
    kb_ids: List[uuid.UUID] = []
    for kb_hex in knowledge_base_ids or []:
        try:
            kb_ids.append(uuid.UUID(kb_hex))
        except ValueError:
            logger.warning(f"[RAG-TOOL] 非法知识库 id 跳过: {kb_hex}")
    if not kb_ids:
        text = (
            "当前无可检索的知识库（知识库 id 列表为空或全部非法）。"
            "请基于常识回答，或如实说明无法从知识库作答。"
        )
        return ToolOutcome(
            text=text,
            docs=[],
            metrics={"reflect_rounds": 0, "retrieved_count": 0, "reranked_count": 0},
        )

    current_query = query
    retrieved: List[dict] = []
    reflect_rounds = 0
    while True:
        reflect_rounds += 1
        new_docs = await asyncio.to_thread(hybrid_retrieve_multi, current_query, kb_ids)
        retrieved = _merge_dedup(retrieved, new_docs)
        if not retrieved:
            break
        # 上下文充分或已达到最大检索轮数上限：跳出反思循环进入重排序
        if reflect_rounds >= CFG.rag_reflect_round_cap:
            break
        if await _context_sufficient(query, _join_context(retrieved)):
            break
        # 上下文不足且仍在轮数内：扩展/改写查询后回到检索
        current_query = await _rewrite_query(query)
        logger.info(f"[RAG-TOOL] 上下文不充分，改写查询重检（第 {reflect_rounds} 轮）")

    top_n = top_k if top_k is not None else CFG.rag_final_top_k
    reranked = await _rerank(query, retrieved, top_n)
    metrics = {
        "reflect_rounds": reflect_rounds,
        "retrieved_count": len(retrieved),
        "reranked_count": len(reranked),
    }
    logger.info(
        f"[RAG-TOOL] 检索完成：candidates={len(retrieved)} → top_k={len(reranked)}"
        f"（reflect_rounds={reflect_rounds}）"
    )
    return ToolOutcome(text=_join_context(reranked), docs=reranked, metrics=metrics)


async def web_search_impl(query: str, top_k: Optional[int] = None) -> ToolOutcome:
    """联网搜索检索（暂未实现）：返回降级提示与空候选，模型据此改走知识库或直接回答。"""
    text = (
        "联网搜索功能暂未实现。请基于知识库检索结果回答；"
        "若知识库中无相关内容，请如实说明无法作答。"
    )
    return ToolOutcome(
        text=text,
        docs=[],
        metrics={"reflect_rounds": 0, "retrieved_count": 0, "reranked_count": 0},
    )


# ---------- 工具 schema（bind_tools 用；返回文本给模型） ----------
@tool
async def knowledge_base_search(
    query: str, knowledge_base_ids: List[str], top_k: Optional[int] = None
) -> str:
    """在用户可见的知识库中检索与问题相关的文档片段（语义 + 关键词混合检索，含重排序）。

    当知识库结果不足以回答问题时可改写 query 后再次调用本工具。

    Args:
        query: 检索查询，应为与用户问题直接相关的独立问句。
        knowledge_base_ids: 目标知识库 id 列表（hex 无连字符），取自请求的 kb_ids。
        top_k: 返回片段数上限（缺省按系统配置）。
    """
    outcome = await knowledge_base_search_impl(query, knowledge_base_ids, top_k)
    return outcome.text


@tool
async def web_search(query: str, top_k: Optional[int] = None) -> str:
    """联网搜索互联网获取最新信息（当前暂未实现）。

    Args:
        query: 检索查询。
        top_k: 返回条数上限（缺省按系统配置）。
    """
    outcome = await web_search_impl(query, top_k)
    return outcome.text


# 工具名 -> 实现函数（返回 ToolOutcome）；respond 节点据此统一分派执行
TOOL_IMPLS = {
    TOOL_KNOWLEDGE_BASE_SEARCH: knowledge_base_search_impl,
    TOOL_WEB_SEARCH: web_search_impl,
}


if __name__ == "__main__":
    # 手动冒烟：不经常态入口调用须先加载配置快照（rewrite/rerank/RAG 参数均读 CFG）
    async def _smoke():
        await CFG.load()
        outcome = await knowledge_base_search_impl(
            "What does Lilian Weng say about types of reward hacking?",
            ["019fa739864b7d9297a65fb8058dbaa1"],
        )
        print(f"metrics={outcome.metrics}")
        for doc in outcome.docs:
            print(doc)

    asyncio.run(_smoke())
