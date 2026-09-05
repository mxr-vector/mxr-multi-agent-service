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
from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent.constants.enums.rag import GradeScore, MessageRole
from agent.prompts.rag import REFLECT_PROMPT, REWRITE_PROMPT
from agent.tools.document import hybrid_retrieve_multi
from core.config_snapshot import CFG
from model.compression.factory import build_compression_model
from model.rerank.factory import get_rerank_client
from utils.env import ENV
from utils.logger import logger

# 工具名常量：respond 节点经 TOOL_IMPLS 按此分派，bind_tools 亦按此构造
TOOL_KNOWLEDGE_BASE_SEARCH = "knowledge_base_search"
TOOL_WIKI_LOOKUP = "kb_wiki_lookup"
TOOL_WEB_SEARCH = "web_search"
TOOL_ENTITY_RELATION_LOOKUP = "entity_relation_lookup"
TOOL_CHUNK_READ = "chunk_read"

# ---------- 工具侧限额常量 ----------
# 检索/导航类工具允许模型传入的 top_k 上限；chat_graph._execute_tool 在分派前
# 做同值收敛（max(1, min(top_k, 20))），两处对应，调整需同步
TOOL_TOP_K_MAX = 20
# 实体关系查询返回条数的缺省值（top_k 未传时生效）
ENTITY_RELATION_DEFAULT_TOP_K = 8
# 实体关系 SQL 单次扫描的行数上限（防御大库把无关行整表拉进内存）
ENTITY_RELATION_SQL_ROW_LIMIT = 2000
# chunk_read 单次调用最多读取的 id 数（防单次读取把上下文窗口撑爆）
CHUNK_READ_MAX_IDS = 5
# chunk_read 单块返回字符的缺省上限 / 硬上限
CHUNK_READ_DEFAULT_MAX_CHARS = 4000
CHUNK_READ_MAX_CHARS = 8000


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
    # Navigation pages are visible to the model but never become answer sources.
    navigation: List[dict] = field(default_factory=list)
    navigation_only: bool = False


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
async def _context_sufficient(question: str, context: str, compressor) -> bool:
    """判断累积检索上下文是否足以回答问题（结构化输出走 function_calling）。

    compressor 为调用方复用的 rewrite/compression 模型实例（同一次工具调用内
    只构造一次，避免反思循环每轮重造）。
    """
    prompt = REFLECT_PROMPT.format(question=question, context=context)
    verdict = (
        await compressor.with_structured_output(
            SufficiencyGrade, method="function_calling"
        ).ainvoke([{"role": MessageRole.USER.value, "content": prompt}])
    )
    return verdict.binary_score == GradeScore.YES.value


async def _rewrite_query(question: str, compressor) -> str:
    """把原问题改写/扩展为检索效果更好的查询（compressor 由调用方复用传入）。"""
    response = await compressor.ainvoke(
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


# ---------- 受控多跳下钻（确定性锚点，不新增在线反思 LLM 调用） ----------
async def _retrieve_hop(
    hop_query: str,
    kb_ids: List[uuid.UUID],
    hop_pool_size: int,
    final_top_k: int,
) -> tuple[List[str], List[dict]]:
    """One hop: independent hybrid recall + independent rerank (own query).

    Returns (pool document ids, reranked docs) so evaluation can attribute
    misses to recall vs merge/trim (design D6).
    """
    docs = await asyncio.to_thread(hybrid_retrieve_multi, hop_query, kb_ids)
    pool = docs[: max(1, hop_pool_size)]
    pool_ids = [str(doc.get("document_id") or "") for doc in pool]
    if not pool:
        return pool_ids, []
    reranked = await _rerank(hop_query, pool, final_top_k)
    return pool_ids, reranked


# ---------- 实体扩展通道（离线索引 + 在线零 LLM，entity-bridge-index 变更） ----------
async def _load_entity_bundles(kb_ids: List[uuid.UUID]) -> list:
    """按库加载实体索引 bundle；表不存在/未构建时返回空列表（静默降级）。"""
    if not ENV.entity_index_enabled:
        return []
    try:
        from entity_index.store import load_entity_bundle

        bundles = []
        for kb_id in kb_ids:
            bundle = await load_entity_bundle(kb_id)
            if bundle is not None:
                bundles.append(bundle)
        return bundles
    except Exception as exc:
        logger.warning(f"[RAG-TOOL] 实体索引加载失败，静默降级: {exc}")
        return []


async def _run_multihop(
    evidence_query: str,
    kb_ids: List[uuid.UUID],
    top_n: int,
    navigation: List[dict] | None,
) -> ToolOutcome:
    """Controlled per-hop evidence retrieval (design D1-D4).

    Hop 0 keeps the original question as the safety base; follow-up hops are
    built from deterministic anchors.  Navigation pages are gated: only pages
    with question-entity/member overlap can contribute hop hints; generic
    pages never touch recall/rerank inputs.  Any hop failure degrades instead
    of blocking, and metrics expose hop_queries/hop_coverage/degraded.
    """
    from agent.tools.multihop import (
        HopResult,
        build_hop_queries,
        collect_hop_pool,
        gate_navigation,
    )

    hop_pool_size = CFG.rag_hop_pool_size
    max_hops = max(1, CFG.rag_max_hops)
    merge_pool_size = max(top_n, CFG.rag_multihop_merge_pool)

    # Hop 0：原问题安全底座（失败即整体降级为空，由调用方兼容处理）
    hop0_pool_ids, hop0_docs = await _retrieve_hop(
        evidence_query, kb_ids, CFG.rag_candidate_pool_size, merge_pool_size
    )
    hop_results: List[HopResult] = [
        HopResult(hop=0, query=evidence_query, docs=hop0_docs)
    ]
    hop_pools: dict[int, List[str]] = {0: hop0_pool_ids}

    # 实体索引：为 wiki 门控提供通用实体统计判据（加载失败/未构建时静默降级）
    entity_bundles = await _load_entity_bundles(kb_ids)
    generic_terms: set[str] | None = None
    if entity_bundles:
        generic_terms = set()
        for bundle in entity_bundles:
            generic_terms |= set(bundle.generic)

    # Wiki 门控：通用页不参与检索决策，仅保持模型可见（统计判据来自实体索引）
    effective_pages, generic_pages = gate_navigation(
        evidence_query, navigation, hop0_docs, generic_terms
    )

    degraded = False
    hop_queries = [
        {"hop": 0, "query": evidence_query, "anchors": [], "source_documents": []}
    ]
    if max_hops > 1:
        queries = build_hop_queries(evidence_query, hop0_docs, effective_pages)
        for index, hop_query in enumerate(queries, start=1):
            if index > max_hops - 1:
                break
            hop_queries.append(
                {
                    "hop": index,
                    "query": hop_query.query,
                    "anchors": list(hop_query.anchors),
                    "source_documents": list(hop_query.source_documents),
                    "member_hint": hop_query.member_hint,
                }
            )
            try:
                pool_ids, docs = await _retrieve_hop(
                    hop_query.query, kb_ids, hop_pool_size, merge_pool_size
                )
                hop_pools[index] = pool_ids
                hop_results.append(
                    HopResult(hop=index, query=hop_query.query, docs=docs)
                )
            except Exception as exc:
                # 后续跳异常不阻断：保留已完成跳的候选并记录降级
                degraded = True
                hop_results.append(
                    HopResult(
                        hop=index,
                        query=hop_query.query,
                        docs=[],
                        ok=False,
                        error=f"{type(exc).__name__}: {exc}"[:200],
                    )
                )
                logger.warning(f"[RAG-TOOL] 多跳第 {index} 跳失败降级: {exc}")

    pool, merge_meta = collect_hop_pool(hop_results, merge_pool_size)
    # 终排：合并池对原问题统一重排（各跳 rerank 分数跨跳不可比，
    # 不在合并层做跨跳比分裁剪；各跳职责是把单路召不回的文档送进决赛圈）
    merged = await _rerank(evidence_query, pool, top_n)
    for doc in merged:
        for hop_index in doc.get("source_hops") or []:
            label = f"hop{hop_index}"
            if label in merge_meta["hop_coverage"]:
                merge_meta["hop_coverage"][label]["in_final"] = True
    metrics = {
        # multihop 为确定性逐跳下钻（无在线反思/改写轮），故记 0 而非 1，
        # 避免 metrics 把多跳路径误标成发生过反思
        "reflect_rounds": 0,
        "retrieved_count": sum(len(r.docs) for r in hop_results),
        "reranked_count": len(merged),
        "merge_pool_count": len(pool),
        "navigation_guided": True,
        "multihop": True,
        "hops_executed": len(hop_results),
        "hop_queries": hop_queries,
        "hop_coverage": merge_meta["hop_coverage"],
        "hop_pools": hop_pools,
        "navigation_effective_pages": len(effective_pages),
        "navigation_generic_pages": len(generic_pages),
        "degraded": degraded,
    }
    logger.info(
        f"[RAG-TOOL] 多跳检索完成：hops={len(hop_results)} → top_k={len(merged)}"
        f"（nav有效页={len(effective_pages)}/{len(navigation or [])}，degraded={degraded}）"
    )
    return ToolOutcome(text=_join_context(merged), docs=merged, metrics=metrics)


# ---------- 工具实现（返回结构化结果，供父图/评测脚本直接调用） ----------
_LEGACY_NAVIGATION_MARKER = "\nNavigation constraints:"


def _split_legacy_navigation_query(query: str) -> tuple[str, bool]:
    """Strip query text produced by older callers without losing its mode flag.

    Navigation metadata used to be serialized into the evidence query.  Keep a
    small compatibility guard for callers that still send that format, but
    never let the metadata reach embedding, BM25, or rerank inputs.
    """
    raw_query = str(query or "").strip()
    evidence_query, marker, _ = raw_query.partition(_LEGACY_NAVIGATION_MARKER)
    if marker:
        return evidence_query.strip(), True
    return raw_query, False


async def knowledge_base_search_impl(
    query: str,
    knowledge_base_ids: List[str],
    top_k: Optional[int] = None,
    navigation: List[dict] | None = None,
    multihop: bool = False,
) -> ToolOutcome:
    """知识库混合检索：混合召回 + 反思自纠错（改写重检）+ 重排序。

    - knowledge_base_ids 为 hex 无连字符列表（非法 id 跳过，空列表返回
      提示文本与空候选，供模型降级回答）；
    - 反思轮数上限 CFG.rag_reflect_round_cap，重排 top-n 取 CFG.rag_final_top_k
      （top_k 入参可覆盖）；
    - Wiki 导航上下文通过独立参数传递，不进入 dense/sparse/rerank 文本；
      导航路径跳过在线反思/改写循环；
    - multihop=True 且 MULTIHOP_ENABLED 时走受控逐跳下钻（确定性锚点，
      无新增 LLM 调用），异常/关闭时回退单轮检索；
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

    evidence_query, legacy_navigation = _split_legacy_navigation_query(query)
    top_n = top_k if top_k is not None else CFG.rag_final_top_k
    # 显式多跳请求：受控逐跳下钻（异常/关闭时安全回退单轮）
    if multihop and ENV.multihop_enabled:
        try:
            return await _run_multihop(evidence_query, kb_ids, top_n, navigation)
        except Exception as exc:
            degraded_reason = f"{type(exc).__name__}: {exc}"[:200]
            logger.warning(f"[RAG-TOOL] 多跳路径异常，回退单轮检索: {exc}")
    else:
        degraded_reason = None

    current_query = evidence_query
    navigation_guided = bool(navigation) or legacy_navigation
    retrieved: List[dict] = []
    reflect_rounds = 0
    # 同一次工具调用内复用同一 rewrite/compression 模型实例，
    # 避免反思循环每轮重造 client（配置快照仍按次请求读取，热更新不受影响）
    compressor = build_compression_model()
    while True:
        reflect_rounds += 1
        new_docs = await asyncio.to_thread(hybrid_retrieve_multi, current_query, kb_ids)
        retrieved = _merge_dedup(retrieved, new_docs)
        if not retrieved:
            break
        # 上下文充分或已达到最大检索轮数上限：跳出反思循环进入重排序
        if navigation_guided or reflect_rounds >= CFG.rag_reflect_round_cap:
            break
        if await _context_sufficient(evidence_query, _join_context(retrieved), compressor):
            break
        # 上下文不足且仍在轮数内：扩展/改写查询后回到检索
        current_query = await _rewrite_query(evidence_query, compressor)
        logger.info(f"[RAG-TOOL] 上下文不充分，改写查询重检（第 {reflect_rounds} 轮）")

    reranked = await _rerank(evidence_query, retrieved, top_n)
    metrics = {
        "reflect_rounds": reflect_rounds,
        "retrieved_count": len(retrieved),
        "reranked_count": len(reranked),
        "navigation_guided": navigation_guided,
        "multihop": False,
    }
    if degraded_reason:
        metrics["degraded"] = True
        metrics["degraded_reason"] = degraded_reason
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


def build_navigation_query(query: str, navigation: List[dict] | None) -> str:
    """Return the evidence query unchanged.

    Kept as a compatibility helper for offline callers.  Wiki pages are
    planning context, not query text: concatenating generic topic summaries
    can displace the question's lexical and semantic signal in the candidate
    pool.  Runtime callers pass the page list through ``navigation`` instead.
    """
    return str(query or "").strip()


async def kb_wiki_lookup_impl(
    query: str,
    knowledge_base_ids: List[str],
    top_k: Optional[int] = None,
) -> ToolOutcome:
    """Search independent topic-page collections for navigation context."""
    if not ENV.wiki_enabled:
        return ToolOutcome(
            text=(
                "Wiki navigation is disabled. Continue with knowledge_base_search "
                "using the evidence-only retrieval path."
            ),
            docs=[],
            metrics={"wiki_hits": 0, "retrieved_count": 0, "reflect_rounds": 0},
            navigation_only=True,
        )
    scopes = [
        str(value).strip() for value in knowledge_base_ids or [] if str(value).strip()
    ]
    if not scopes:
        return ToolOutcome(
            text=(
                "No wiki topic index is configured for this request. "
                "Fall back to knowledge_base_search."
            ),
            docs=[],
            metrics={"wiki_hits": 0, "retrieved_count": 0, "reflect_rounds": 0},
            navigation_only=True,
        )
    limit = max(1, min(int(top_k or 5), TOOL_TOP_K_MAX))
    try:
        from wiki.storage import search_topic_pages

        hits = await asyncio.to_thread(search_topic_pages, query, scopes, limit)
    except Exception as exc:
        logger.warning(f"[WIKI-TOOL] topic lookup failed, falling back: {exc}")
        hits = []
    if not hits:
        return ToolOutcome(
            text=(
                "The wiki topic index is empty or unavailable. "
                "No navigation result was found; continue with knowledge_base_search."
            ),
            docs=[],
            metrics={"wiki_hits": 0, "retrieved_count": 0, "reflect_rounds": 0},
            navigation_only=True,
        )
    navigation = [hit.to_dict() for hit in hits]
    lines = [
        "Topic navigation results (navigation only; verify facts with evidence search):"
    ]
    for index, page in enumerate(navigation, start=1):
        lines.append(
            f"[{index}] {page.get('title', '')}\n"
            f"summary: {page.get('summary', '')}\n"
            f"keywords: {', '.join(page.get('keywords') or [])}\n"
            f"entities: {', '.join(page.get('entities') or [])}\n"
            f"representative questions: {' | '.join(page.get('representative_questions') or [])}\n"
            f"member document ids: {', '.join(page.get('documents') or [])}\n"
            f"related topics: {', '.join(page.get('related_topics') or [])}"
        )
        if page.get("staleness_notice"):
            lines.append(f"notice: {page['staleness_notice']}")
    return ToolOutcome(
        text="\n\n".join(lines),
        docs=[],
        metrics={
            "wiki_hits": len(navigation),
            "retrieved_count": 0,
            "reflect_rounds": 0,
        },
        navigation=navigation,
        navigation_only=True,
    )


# ---------- 工具 schema（bind_tools 用；返回文本给模型） ----------
@tool
async def knowledge_base_search(
    query: str,
    knowledge_base_ids: List[str],
    top_k: Optional[int] = None,
    multihop: bool = False,
) -> str:
    """在用户可见的知识库中检索与问题相关的文档片段（语义 + 关键词混合检索，含重排序）。

    对多跳、主题模糊或跨文档问题，先调用 kb_wiki_lookup，再基于返回的导航
    上下文规划证据检索；不要把主题摘要、关键词或代表性问题拼接进 query。
    本工具结果才是可引用的事实证据。

    Args:
        query: 检索查询，应为与用户问题直接相关的独立问句。
        knowledge_base_ids: 目标知识库 id 列表（hex 无连字符），取自请求的 kb_ids。
        top_k: 返回片段数上限（缺省按系统配置）。
        multihop: 问题明确需要跨实体/跨文档逐步推理时置 True，将逐跳召回并
            合并各跳证据；单跳/普通问题保持 False。
    """
    outcome = await knowledge_base_search_impl(
        query, knowledge_base_ids, top_k, multihop=multihop
    )
    return outcome.text


@tool
async def kb_wiki_lookup(
    query: str, knowledge_base_ids: List[str], top_k: Optional[int] = None
) -> str:
    """查询独立的 LLM Wiki 主题地图，用于多跳/主题模糊/跨文档问题导航。

    该工具只返回主题级导航字段（主题概述、关键词、实体、代表性问题、成员文档
    指针和相关主题），不应直接作为答案证据；随后调用 knowledge_base_search 取证。
    主题索引为空时会返回明确的降级提示，问答应继续走证据检索。
    """
    outcome = await kb_wiki_lookup_impl(query, knowledge_base_ids, top_k)
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


# ---------- 分层确定性工具（agentic-relation-retrieval：零在线 LLM） ----------
async def entity_relation_lookup_impl(
    entity: str,
    knowledge_base_ids: List[str],
    top_k: Optional[int] = None,
) -> ToolOutcome:
    """按实体查询类型化关系与桥接事实句（关系索引，零 LLM）。

    关系表缺失/实体无记录时返回空结果提示，不报错不阻断。
    """
    from sqlalchemy import text as sql
    from database.postgre_client import get_async_engine

    top_n = max(1, min(top_k or ENTITY_RELATION_DEFAULT_TOP_K, TOOL_TOP_K_MAX))
    entity_norm = (entity or "").strip().casefold()
    if not entity_norm:
        return ToolOutcome(
            text="实体关系查询：实体为空。", docs=[], metrics={"relations": 0}
        )
    kb_uuids = []
    for kb in knowledge_base_ids or []:
        try:
            kb_uuids.append(uuid.UUID(str(kb)))
        except ValueError:
            continue
    rows: list = []
    if kb_uuids:
        # 复用进程级共享引擎（连接池），避免每次工具调用重建引擎/dispose 的开销
        engine = get_async_engine()
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        sql(
                            "SELECT head_entity, tail_entity, relation, fact_text, "
                            "chunk_id, document_id FROM rag.entity_index_relations "
                            "WHERE kb_id = ANY(:kbs) AND (head_entity=:e OR tail_entity=:e) "
                            f"LIMIT {ENTITY_RELATION_SQL_ROW_LIMIT}"
                        ),
                        {"kbs": kb_uuids, "e": entity_norm},
                    )
                ).all()
        except Exception as exc:  # 表缺失/连接异常：静默降级为空结果（调用方继续对话）
            logger.warning(f"[RAG-TOOL] 关系索引查询降级: {exc}")
            rows = []
    # 按（对端实体, 关系）聚合：频次 + 首条事实句 + 来源指针（id 统一无连字符 hex，
    # 与 chunk_read 入参约定一致）
    agg: dict[tuple, dict] = {}
    for row in rows:
        other = row.tail_entity if row.head_entity == entity_norm else row.head_entity
        key = (other, row.relation)
        item = agg.get(key)
        if item is None:
            agg[key] = {
                "other": other,
                "relation": row.relation,
                "fact": row.fact_text,
                "chunk_id": row.chunk_id.hex,
                "document_id": row.document_id.hex,
                "count": 1,
            }
        else:
            item["count"] += 1
    ranked = sorted(agg.values(), key=lambda item: -item["count"])[:top_n]
    if not ranked:
        return ToolOutcome(
            text=f"实体关系查询：实体「{entity}」没有关系记录。",
            docs=[],
            metrics={"relations": 0, "entity": entity_norm},
        )
    lines = []
    for item in ranked:
        fact = (item["fact"] or "").strip()
        lines.append(
            f"- {item['other']} | {item['relation']}（出现 {item['count']} 次）"
            + (f" | 事实: {fact[:200]}" if fact else "")
            + f" | chunk_id={item['chunk_id']}"
        )
    text_out = (
        f"实体「{entity}」的关系（可用 chunk_read 读取来源块全文）：\n"
        + "\n".join(lines)
    )
    return ToolOutcome(
        text=text_out,
        docs=[],
        metrics={
            "relations": len(ranked),
            "entity": entity_norm,
            "raw_rows": len(rows),
        },
    )


async def chunk_read_impl(
    ids: List[str],
    max_chars: Optional[int] = None,
    knowledge_base_ids: List[str] | None = None,
) -> ToolOutcome:
    """按块/文档 id 读取原文（限量截断，零 LLM）。

    id 优先按叶块解析；未命中时按文档取其首个叶块。不存在则跳过。
    提供 knowledge_base_ids 时按库作用域过滤（防跨库读取）。
    """
    from sqlalchemy import text as sql
    from database.postgre_client import get_async_engine

    per_chars = max(
        200,
        min(max_chars or CHUNK_READ_DEFAULT_MAX_CHARS, CHUNK_READ_MAX_CHARS),
    )
    clean = [str(i).strip() for i in (ids or []) if str(i).strip()][:CHUNK_READ_MAX_IDS]
    if not clean:
        return ToolOutcome(
            text="块读取：未提供有效 id。", docs=[], metrics={"chunks": 0}
        )
    # 输入 → 规范化带连字符 UUID 串（found 键的规范形）；带/不带连字符均可命中
    norm: dict[str, str] = {}
    uuids = []
    for item in clean:
        try:
            parsed = uuid.UUID(item)
        except ValueError:
            continue
        uuids.append(parsed)
        norm[item] = str(parsed)
    if not uuids:
        return ToolOutcome(text="块读取：无有效 id。", docs=[], metrics={"chunks": 0})
    # KB 作用域：块表无 kb 列，经文档表关联过滤。
    # None=未传作用域（兼容旧调用，不限制）；空列表=无可用范围，显式拒绝，
    # 防止调用方把空集误当全库放行
    kb_uuids = []
    for kb in knowledge_base_ids or []:
        try:
            kb_uuids.append(uuid.UUID(str(kb)))
        except ValueError:
            continue
    if knowledge_base_ids is not None and not kb_uuids:
        return ToolOutcome(
            text="块读取：当前无可用知识库范围，无法读取。",
            docs=[],
            metrics={"chunks": 0},
        )
    scope = (
        " AND c.document_id IN (SELECT id FROM rag.rag_documents WHERE knowledge_base_id = ANY(:kbs))"
        if kb_uuids
        else ""
    )
    # 复用进程级共享引擎（连接池），避免每次工具调用重建引擎/dispose 的开销
    engine = get_async_engine()
    found: dict[str, dict] = {}
    try:
        async with engine.connect() as conn:
            params: dict = {"ids": uuids}
            if kb_uuids:
                params["kbs"] = kb_uuids
            by_chunk = (
                await conn.execute(
                    sql(
                        "SELECT c.id, c.document_id, c.content FROM rag.rag_chunks c "
                        f"WHERE c.id = ANY(:ids){scope}"
                    ),
                    params,
                )
            ).all()
            for row in by_chunk:
                found[str(row.id)] = {
                    "chunk_id": row.id.hex,
                    "document_id": row.document_id.hex,
                    "content": row.content or "",
                }
            missing = [u for u in uuids if str(u) not in found]
            if missing:
                doc_params: dict = {"ids": missing}
                if kb_uuids:
                    doc_params["kbs"] = kb_uuids
                by_doc = (
                    await conn.execute(
                        sql(
                            "SELECT DISTINCT ON (c.document_id) c.id, c.document_id, c.content "
                            f"FROM rag.rag_chunks c WHERE c.document_id = ANY(:ids) AND c.level=0{scope} "
                            "ORDER BY c.document_id, c.chunk_index"
                        ),
                        doc_params,
                    )
                ).all()
                for row in by_doc:
                    found[str(row.document_id)] = {
                        "chunk_id": row.id.hex,
                        "document_id": row.document_id.hex,
                        "content": row.content or "",
                    }
    except Exception as exc:
        logger.warning(f"[RAG-TOOL] 块读取降级: {exc}")
    lines = []
    docs_out: List[dict] = []
    for item in clean:
        hit = found.get(norm.get(item, ""))
        if hit is None:
            continue
        lines.append(
            f"[chunk_id={hit['chunk_id']} document_id={hit['document_id']}]\n"
            f"{hit['content'][:per_chars]}"
        )
        docs_out.append(
            {
                "document_id": hit["document_id"],
                "chunk_id": hit["chunk_id"],
                "text": hit["content"][:per_chars],
            }
        )
    if not lines:
        return ToolOutcome(
            text="块读取：未找到对应块。", docs=[], metrics={"chunks": 0}
        )
    return ToolOutcome(
        text="\n\n".join(lines), docs=docs_out, metrics={"chunks": len(lines)}
    )


@tool
async def entity_relation_lookup(
    entity: str, knowledge_base_ids: List[str], top_k: Optional[int] = None
) -> str:
    """按实体查询其类型化关系与桥接事实句（离线构建的关系索引，确定性结果）。

    多跳推理中发现桥接实体时使用：返回该实体参与的关系、对端实体、承载事实的
    原句与来源块指针；可再用 chunk_read 读取来源块全文，或用对端实体继续检索。
    关系索引未构建或实体无记录时会返回明确提示，应改走 knowledge_base_search。

    Args:
        entity: 要查询的实体名称（与文本中出现的写法一致）。
        knowledge_base_ids: 目标知识库 id 列表（hex 无连字符），取自请求的 kb_ids。
        top_k: 返回关系条数上限（缺省 8）。
    """
    outcome = await entity_relation_lookup_impl(entity, knowledge_base_ids, top_k)
    return outcome.text


@tool
async def chunk_read(
    ids: List[str],
    max_chars: Optional[int] = None,
    knowledge_base_ids: Optional[List[str]] = None,
) -> str:
    """按块或文档 id 读取原文全文（每段限量截断）。

    当检索片段被截断、需要核验上下文，或关系查询返回的来源块需要通读时使用。
    id 优先按叶块解析，未命中时按文档取其首个叶块；不存在的 id 会被跳过。
    仅能读取 knowledge_base_ids 范围内的块（缺省时按当前请求的知识库）。

    Args:
        ids: 块 id 或文档 id 列表（hex 无连字符，最多 5 个）。
        max_chars: 每块返回字符上限（缺省 4000）。
        knowledge_base_ids: 允许读取的知识库 id 列表（hex 无连字符），取自请求的 kb_ids。
    """
    outcome = await chunk_read_impl(ids, max_chars, knowledge_base_ids)
    return outcome.text


# 工具名 -> 实现函数（返回 ToolOutcome）；respond 节点据此统一分派执行
TOOL_IMPLS = {
    TOOL_KNOWLEDGE_BASE_SEARCH: knowledge_base_search_impl,
    TOOL_WIKI_LOOKUP: kb_wiki_lookup_impl,
    TOOL_WEB_SEARCH: web_search_impl,
    TOOL_ENTITY_RELATION_LOOKUP: entity_relation_lookup_impl,
    TOOL_CHUNK_READ: chunk_read_impl,
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
