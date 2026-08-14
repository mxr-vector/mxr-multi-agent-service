"""
zai-org/LongBench 多语言（中英）双路召回评测适配器（诊断性披露）。

LongBench 是问答数据集（无标准 retrieval qrels），本适配器采用"可辩护证据"
映射口径（v2）：query 的 answer 大小写不敏感子串命中 context 段落，则该段落
为 gold（段落级 → 文档级）；完整 answer 不可定位时，取答案最长 N 个标点切分
片段兜底匹配（改写式答案，中英文通用）；命中段落数超过上限的 query 视为答案
过泛（answer_too_ambiguous），不参与指标、不伪造 MRR。建库按段落文本跨
query/子集去重（相同段落复用同一文档），避免重复副本稀释检索排名。

- 多语言构成：默认 5 个 QA 类子集（字段统一为 input/context/answers/_id）
  中文 dureader/multifieldqa_zh + 英文 2wikimqa/musique/hotpotqa；
  全量 1,000 条（每子集 200 条全量），--subsets 可换。
- 建库：每条 query 的 context 按换行切分为段落，每段落一个文档（单块；
  超长段落走 ingest_file 切块），source_uri=lb:{subset}:{qid}:{para_idx}；
  段落文本跨 query/子集按 hash 去重，重复段落复用既有文档。
- 管线：hybrid_retrieve_multi（dense + jieba BM25 RRF，candidate_pool=50）
  + rerank 精排（Qwen3-Embedding-4B cohere 协议），与生产配置一致。
- 指标：Recall@K / Precision@K / NDCG@K / MRR（K∈{1,3,5,10}，文档级，宏平均±std），
  仅统计可辩护 query；结果标注"诊断性，不参与严格对比"。
- 产物：
  - gold/longbench_doc_map.json：lb 标识 → PG 文档 id 映射
  - results/longbench_dual_results.json：逐 query 明细
  - results/longbench_dual_summary.json：整体汇总 + why 统计
  - results/longbench_{subset}_summary.json：每子集独立汇总
  - results/longbench_dual_report.md：报告（整体表 + 按子集分节标注中英文/任务类型）

数据来源（HF）：zai-org/LongBench（THUDM/LongBench 镜像）data.zip →
data/ 目录下各子集 jsonl（仅需上述 5 个文件）。

用法：
  uv run python test/dataset01/eval/longbench_eval.py [--force] [--cleanup]
      [--subsets s1,s2,...] [--max-queries 1000] [--no-rerank]
      [--pool 50] [--retry-failed]
"""

import argparse
import asyncio
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from common import BASE_K_VALUES, DATA_DIR, GOLD_DIR, RESULTS_DIR, ensure_cfg_async, load_json, normalize, save_json

from dual_retrieval import (
    cleanup_kb,
    create_kb,
    find_kb,
    fmt_ms,
    get_eval_session,
    ingest_document_retry,
    report_lines,
    run_eval,
    sha256_of_text,
    summarize,
    vectorize_batch,
)

# 评测知识库按子集分库：每子集独立语料库（dataset01-longbench-{subset}），
# 检索在子集自身语料内进行，避免跨子集语料污染
KB_NAME_PREFIX = "dataset01-longbench"
KB_DESCRIPTION = "RAG 双路召回评测语料库：LongBench {subset} 子集（context 段落单块，诊断性）"

# 中英 QA 类子集（字段统一：input/context/answers/_id；按子集顺序拼接）
SUBSETS = [
    "dureader",
    "2wikimqa",
    "musique",
    "hotpotqa",
    "multifieldqa_zh",
]
# 子集元数据：语言与任务类型标注（报告分节使用）
SUBSET_INFO = {
    "dureader": {"lang": "中文", "task": "多文档 QA"},
    "2wikimqa": {"lang": "英文", "task": "多跳 QA"},
    "musique": {"lang": "英文", "task": "多跳 QA"},
    "hotpotqa": {"lang": "英文", "task": "多跳 QA"},
    "multifieldqa_zh": {"lang": "中文", "task": "单文档 QA"},
}
# 默认评测条数：5 子集全量 1,000 条（每子集 200 条全量，无需截断）
DEFAULT_MAX_QUERIES = 1000
DOC_MAP_PATH = GOLD_DIR / "longbench_doc_map.json"
RESULTS_PATH = RESULTS_DIR / "longbench_dual_results.json"
SUMMARY_PATH = RESULTS_DIR / "longbench_dual_summary.json"

# ---- 可辩护证据映射口径参数（v2）---------------------------------------------
# 片段兜底匹配的最小片段长度（字符）：过短片段（如英文冠词）命中面过广，误报率高
GOLD_FRAG_MIN_LEN = 4
# 每个答案最多取前 N 个最长片段参与兜底匹配
GOLD_FRAG_MAX_COUNT = 3
# gold 段落数上限：超过视为答案过泛（如常见词命中文档池大量段落），
# 子串匹配无法区分证据段落，判为 answer_too_ambiguous 不参与指标
MAX_GOLD_PARAS = 10
# 口径版本：进建库指纹；口径参数变更后旧 doc map 指纹不匹配，强制重建
GOLD_ORACLE_VERSION = "v2"
# 答案标点切分模式（中英文常用标点 + 空白）
_PUNCT_RE = re.compile(r"[。！？；，、,.!?;:\"'《》〈〉（）()\[\]【】\s]+")


def _data_path(subset: str) -> Path:
    return DATA_DIR / "longbench_data" / "data" / f"{subset}.jsonl"


def _kb_name(subset: str) -> str:
    """子集独立评测知识库名。"""
    return f"{KB_NAME_PREFIX}-{subset}"


def _require_data(subsets: list[str]) -> None:
    missing = [s for s in subsets if not _data_path(s).exists()]
    if missing:
        raise SystemExit(
            f"缺少数据文件: {[str(_data_path(s)) for s in missing]}\n"
            "请从 HF 下载 zai-org/LongBench（THUDM/LongBench 镜像）data.zip "
            "并解压到 test/dataset01/data/longbench_data/（HF_ENDPOINT=https://hf-mirror.com）"
        )


def split_paragraphs(context: str) -> list[str]:
    """context 按换行切分为非空段落（去首尾空白）。"""
    return [p.strip() for p in context.split("\n") if p.strip()]


def answer_fragments(answer: str) -> list[str]:
    """答案按标点切分后的非空片段（规范化去重、按长度降序取前 N 个）。

    改写式答案（中文长句 / 英文列表）无法整串定位时用于兜底匹配。
    """
    frags = {normalize(f) for f in _PUNCT_RE.split(answer)}
    return sorted(
        (f for f in frags if len(f) >= GOLD_FRAG_MIN_LEN),
        key=lambda f: (-len(f), f),  # 同长度按字典序，保证跨进程确定性
    )[:GOLD_FRAG_MAX_COUNT]


def defensible_paragraphs(context: str, answers: list[str]) -> tuple[list[int], str | None]:
    """可辩护证据映射（v2）：answer 定位到 context 段落 → 段落下标列表。

    匹配顺序（大小写不敏感）：
    1. 完整答案子串命中段落（强证据）；
    2. 完整答案不可定位时，取答案最长 N 个标点切分片段兜底（改写式答案）。
    命中段落数超过 MAX_GOLD_PARAS 视为答案过泛（answer_too_ambiguous，
    子串匹配无法区分证据段落），不参与指标。
    返回 (gold_para_idx, why)；why 为 None 表示可辩护。
    """
    paras = split_paragraphs(context)
    norm_paras = [normalize(p).casefold() for p in paras]
    gold: set[int] = set()
    for a in answers:
        na = normalize(a).casefold()
        if not na:
            continue
        hits = {i for i, np in enumerate(norm_paras) if na in np}
        if hits:
            gold |= hits
            continue
        for frag in answer_fragments(a):
            ff = frag.casefold()
            for i, np in enumerate(norm_paras):
                if ff in np:
                    gold.add(i)
    if not gold:
        return [], "answer_not_in_context"
    if len(gold) > MAX_GOLD_PARAS:
        return [], "answer_too_ambiguous"
    return sorted(gold), None


def load_rows(subsets: list[str]) -> list[dict]:
    """读多个子集 jsonl（顺序拼接），统一字段为 subset/qid/question/context/answers。

    qid 以 {subset}:{_id} 唯一化（各子集 _id 独立编号，跨子集会重复）。
    """
    import json

    rows = []
    for subset in subsets:
        path = _data_path(subset)
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                raw = json.loads(line)
                rows.append(
                    {
                        "subset": subset,
                        "qid": f"{subset}:{raw['_id']}",
                        "question": str(raw.get("input") or ""),
                        "context": str(raw.get("context") or ""),
                        "answers": [str(a) for a in (raw.get("answers") or [])],
                    }
                )
    return rows


async def build(session_factory, rows: list[dict], force: bool, batch_size: int = 100) -> object:
    """按子集分库建库（幂等：各库与 doc map 指纹一致时复用；--force 重建）。

    每个子集一个独立评测知识库（dataset01-longbench-{subset}），检索在子集
    自身语料内进行，避免跨子集语料污染；子集内按段落文本跨 query 去重。
    摄入走 ingest_document_retry（独立 session + DB 异常重试），
    规避评测目标机 PG 间歇断连。
    """
    subsets = sorted({r["subset"] for r in rows})
    fp = hashlib.sha256(
        (
            "\n".join(r["subset"] + r["qid"] + r["context"][:200] for r in rows)
            + f"|per-subset-kb|dedup|gold:{GOLD_ORACLE_VERSION}"
            f"|frag:{GOLD_FRAG_MIN_LEN}:{GOLD_FRAG_MAX_COUNT}"
            f"|max:{MAX_GOLD_PARAS}"
        ).encode("utf-8")
    ).hexdigest()[:16]

    kb_by_subset: dict[str, object] = {}
    async with session_factory() as session:
        for subset in subsets:
            kb_name = _kb_name(subset)
            existing = await find_kb(session, kb_name)
            if existing is not None and force:
                print(f"[lb] --force：清理既有评测知识库 {kb_name}...")
                await cleanup_kb(session, kb_name)
            if existing is None or force:
                kb = await create_kb(session, kb_name, KB_DESCRIPTION.format(subset=subset))
                await session.commit()
                print(
                    f"[lb] 已创建评测知识库: {kb_name} id={kb.id.hex}"
                    f" collection={kb.qdrant_collection}"
                )
            else:
                kb = existing
            kb_by_subset[subset] = kb

    if not force:
        if DOC_MAP_PATH.exists():
            cached = load_json(DOC_MAP_PATH)
            if cached.get("fingerprint") == fp and set(cached.get("kb_ids", {})) == set(subsets):
                print(
                    f"[lb] 评测知识库已存在且指纹一致（{len(subsets)} 个子集库），"
                    f"复用 {len(cached['mapping'])} 个段落映射（重建请加 --force）"
                )
                return kb_by_subset, cached["mapping"]
        print(
            "[lb] 评测知识库已存在但指纹不一致（重建请加 --force），继续使用既有库"
        )
        return kb_by_subset, {}

    mapping: dict[str, str] = {}
    total_leaves = 0
    processed = 0
    dup_skipped = 0
    for subset in subsets:
        kb = kb_by_subset[subset]
        pending_specs: list[dict] = []
        # 段落文本 hash → 首个 uri：子集内相同文本跨 query 复用既有文档，
        # 避免重复副本在检索排名中占位稀释命中（多跳子集段落池重叠率高）
        seen_texts: dict[str, str] = {}
        for row in rows:
            if row["subset"] != subset:
                continue
            for para_idx, para in enumerate(split_paragraphs(row["context"])):
                uri = f"lb:{row['qid']}:{para_idx}"
                text_hash = sha256_of_text(para)
                if text_hash in seen_texts:
                    mapping[uri] = mapping[seen_texts[text_hash]]
                    dup_skipped += 1
                    continue
                seen_texts[text_hash] = uri
                ingested, leaf_specs = await ingest_document_retry(
                    session_factory,
                    kb,
                    title=uri,
                    text=para,
                    source_uri=uri,
                    source_system="LongBench",
                    metadata={"subset": row["subset"], "lb_qid": row["qid"], "para_idx": para_idx},
                )
                if ingested is None:
                    continue
                mapping[uri] = ingested.id.hex
                total_leaves += len(leaf_specs)
                pending_specs.extend(leaf_specs)
                processed += 1
                if processed % batch_size == 0:
                    await vectorize_batch(kb, pending_specs)
                    print(f"[lb] 向量化 {processed} 段落（累计叶块 {total_leaves}）")
                    pending_specs = []
        if pending_specs:
            await vectorize_batch(kb, pending_specs)
            print(f"[lb] 向量化收尾（累计叶块 {total_leaves}）")

    save_json(
        DOC_MAP_PATH,
        {
            "dataset": f"zai-org/LongBench {'+'.join({r['subset'] for r in rows})}",
            "fingerprint": fp,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "kb_ids": {s: kb_by_subset[s].id.hex for s in subsets},
            "mapping": mapping,
        },
    )
    print(
        f"[lb] 建库完成：{len(mapping)} 段落映射 / {processed} 唯一文档"
        f"（复用重复段落 {dup_skipped}）/ {total_leaves} 叶块（{len(subsets)} 个子集库）"
    )
    return kb_by_subset, mapping


def build_queries(rows: list[dict], mapping: dict[str, str], kb_by_subset: dict) -> list[dict]:
    """构建评测 query 列表（gold = 可辩护段落 → PG 文档 id，按文档去重）。"""
    queries = []
    for row in rows:
        gold_docs = sorted(
            {
                mapping[f"lb:{row['qid']}:{i}"]
                for i in row["gold_para_idx"]
                if f"lb:{row['qid']}:{i}" in mapping
            }
        )
        queries.append(
            {
                "qid": row["qid"],
                "subset": row["subset"],
                "question": row["question"],
                "gold_docs": gold_docs,
                "why": row["why"],
                "kb": kb_by_subset[row["subset"]],
            }
        )
    return queries


def _subset_of(qid: str) -> str:
    """从 qid（{subset}:{_id}）提取子集名。"""
    return qid.split(":", 1)[0]


def _subset_section_lines(
    subset: str, summary: dict, ks: Sequence[int]
) -> list[str]:
    """单子集报告分节：标题（含中英文/任务类型标注）+ 独立指标表 + 可辩护统计。"""
    info = SUBSET_INFO.get(subset, {})
    label = f"{subset}（{info.get('lang', '')}，{info.get('task', '')}）"
    counts = summary["counts"]
    metrics = summary["metrics"]
    lines = [
        f"### {label}",
        "",
        f"- 执行 query：{counts['valid'] + counts['empty_gold'] + counts['failed']} 条"
        f"（有效 {counts['valid']} / gold 为空 {counts['empty_gold']} / 失败 {counts['failed']}）",
    ]
    if summary.get("why"):
        lines.append(f"- 不可辩护统计：{summary['why']}")
    lines.extend(["", "| K | Recall@K | Precision@K | NDCG@K |", "|---|---|---|---|"])
    for k in ks:
        k = int(k)
        lines.append(
            f"| {k} | {fmt_ms(metrics[k]['recall'])} | {fmt_ms(metrics[k]['precision'])} | {fmt_ms(metrics[k]['ndcg'])} |"
        )
    lines.append(f"| MRR | {fmt_ms(metrics['mrr'])} | — | — |")
    return lines


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="LongBench 多语言（zh/en）双路召回评测（诊断性）"
    )
    parser.add_argument("--force", action="store_true", help="已存在评测知识库时清理重建")
    parser.add_argument("--cleanup", action="store_true", help="整体删除评测知识库后退出")
    parser.add_argument(
        "--subsets",
        type=str,
        default=",".join(SUBSETS),
        help=f"评测子集列表（逗号分隔，默认全 5 个）",
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=DEFAULT_MAX_QUERIES,
        help=f"仅评测前 N 条 query（默认 {DEFAULT_MAX_QUERIES}；冒烟可设小值）",
    )
    parser.add_argument("--no-rerank", action="store_true", help="跳过 rerank（仅双路召回检索层）")
    parser.add_argument("--pool", type=int, default=None, help="候选池大小（默认取系统 RAG_CANDIDATE_POOL_SIZE）")
    parser.add_argument("--retry-failed", action="store_true", help="仅补跑上次失败（status!=ok）的 query 并合并结果")
    args = parser.parse_args()

    await ensure_cfg_async()
    from core.config_snapshot import CFG

    subsets = [s.strip() for s in args.subsets.split(",") if s.strip()]
    _require_data(subsets)
    pool_size = args.pool or CFG.rag_candidate_pool_size

    if args.cleanup:
        async with get_eval_session() as session:
            for subset in subsets:
                kb_name = _kb_name(subset)
                removed = await cleanup_kb(session, kb_name)
                print(
                    f"[lb] 已删除评测知识库 {kb_name}"
                    if removed
                    else f"[lb] 评测知识库 {kb_name} 不存在"
                )
        return

    rows = load_rows(subsets)
    from collections import Counter

    per_subset = Counter(r["subset"] for r in rows)
    print(f"[lb] 数据就绪：{len(rows)} 条 query（{dict(per_subset)}）")

    # 可辩护证据映射（建库前完成，gold 为段落 → 文档）
    for row in rows:
        gold_idx, why = defensible_paragraphs(row["context"], row["answers"])
        row["gold_para_idx"] = gold_idx
        row["why"] = why
    defensible = sum(1 for r in rows if r["gold_para_idx"])
    why_counter = Counter(r["why"] for r in rows if r["why"])
    print(
        f"[lb] 可辩护 query：{defensible}/{len(rows)}"
        f"（answer 可定位到 context 段落）；不可辩护：{dict(why_counter)}"
        "，不参与指标"
    )

    async with get_eval_session() as session:
        kb_by_subset, mapping = await build(get_eval_session, rows, args.force)
        if not mapping:
            from sqlalchemy import select

            from entity.rag.document import Document

            mapping = {}
            for subset, kb in kb_by_subset.items():
                stmt = select(Document.id, Document.source_uri).where(
                    Document.knowledge_base_id == kb.id
                )
                found = (await session.execute(stmt)).all()
                mapping.update({r.source_uri: r.id.hex for r in found})
            print(f"[lb] 从 PG 重建段落映射：{len(mapping)} 个")

    queries = build_queries(rows, mapping, kb_by_subset)
    if args.max_queries:
        queries = queries[: args.max_queries]
    executed = Counter(q["subset"] for q in queries)
    print(
        f"[lb] 执行 {len(queries)} 条 query（{dict(executed)}；"
        f"其中可辩护 {sum(1 for q in queries if q['gold_docs'])} 条）"
    )

    if args.retry_failed:
        if not RESULTS_PATH.exists():
            raise SystemExit(f"--retry-failed 需要已有结果文件: {RESULTS_PATH}")
        prev = load_json(RESULTS_PATH)
        failed_qids = {r["qid"] for r in prev["results"] if r["status"] != "ok"}
        if not failed_qids:
            print("[lb] 无失败 query，无需补跑")
            return
        retry = [q for q in queries if q["qid"] in failed_qids]
        print(f"[lb] 补跑失败 query：{len(retry)} 条")
        fresh = await run_eval(retry, kb_by_subset, pool_size, use_rerank=not args.no_rerank)
        by_qid = {r["qid"]: r for r in fresh}
        merged = [by_qid.get(r["qid"], r) for r in prev["results"]]
        results = merged
        payload = {
            **prev,
            "results": results,
            "meta": {
                **prev["meta"],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "retried_failed": len(retry),
            },
        }
        print(
            f"[lb] 合并后结果：{len(results)} 条"
            f"（失败 {sum(1 for r in results if r['status'] != 'ok')}）"
        )
    else:
        results = await run_eval(queries, kb_by_subset, pool_size, use_rerank=not args.no_rerank)
        payload = {
            "meta": {
                "dataset": f"zai-org/LongBench 多语言（{'/'.join(subsets)}）",
                "kb_id": "各子集独立库（"
                + ", ".join(f"{s}={kb_by_subset[s].id.hex[:8]}" for s in subsets)
                + "）",
                "pool_size": pool_size,
                "rerank": not args.no_rerank,
                "subsets": subsets,
                "executed_queries": len(queries),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            "results": results,
        }
    save_json(RESULTS_PATH, payload)

    summary = summarize(results, BASE_K_VALUES)
    summary["meta"] = payload["meta"]
    summary["why"] = dict(Counter(q["why"] for q in queries if q["why"]))
    save_json(SUMMARY_PATH, summary)

    # 按子集拆分汇总：每子集独立 summary 落盘（供分节报告与断点续跑）
    per_subset: dict[str, dict] = {}
    for subset in subsets:
        sub_results = [r for r in results if _subset_of(r["qid"]) == subset]
        sub_queries = [q for q in queries if _subset_of(q["qid"]) == subset]
        sub_summary = summarize(sub_results, BASE_K_VALUES)
        sub_summary["meta"] = payload["meta"]
        sub_summary["why"] = dict(Counter(q["why"] for q in sub_queries if q["why"]))
        per_subset[subset] = sub_summary
        save_json(RESULTS_DIR / f"longbench_{subset}_summary.json", sub_summary)

    lines = report_lines(
        "LongBench 多语言（zh/en）双路召回评测报告（诊断性）",
        payload["meta"],
        summary,
        BASE_K_VALUES,
        extra=[
            f"- 可辩护 query：{summary['counts']['valid']}/{len(queries)}"
            f"（answer 可定位到 context 段落）；不可辩护统计：{summary.get('why')}",
            "",
            f"> 诊断性披露：LongBench 无标准 retrieval qrels，gold 为可辩护证据映射（{GOLD_ORACLE_VERSION}）："
            "完整 answer 大小写不敏感子串命中 context 段落（不可定位时取答案最长"
            f"{GOLD_FRAG_MAX_COUNT} 个标点切分片段兜底，片段长度≥{GOLD_FRAG_MIN_LEN}）；"
            f"命中段落数超过 {MAX_GOLD_PARAS} 的 query 视为答案过泛（answer_too_ambiguous）不参与指标；"
            "每子集独立知识库，库内按段落文本跨 query 去重（重复段落复用同一文档）；"
            "不可辩护 query 不伪造 MRR。结果仅供参考，不参与严格对比。",
            "",
            "> 口径限定：本评测为检索层下界（原始 query 单轮混合召回 + rerank），不含生产 Agentic 管线的"
            "LLM 改写、工具内反思重检与自主决策检索；gold 仅覆盖答案所在段落，多跳的桥接证据段落未测量；"
            "短答案 query 剔除与片段兜底 gold 膨胀的偏差详见 RAG.md 4.2 节。",
        ],
    )
    lines.extend(["", "## 按子集拆分（中英文 / 任务类型标注）", ""])
    for subset in subsets:
        lines.extend(_subset_section_lines(subset, per_subset[subset], BASE_K_VALUES))
        lines.append("")
    report_path = RESULTS_DIR / "longbench_dual_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[lb] 汇总已落盘: {SUMMARY_PATH}；分集汇总: {len(per_subset)} 份；报告: {report_path}")
    m = summary["metrics"]
    if m["mrr"]:
        print(
            f"[lb] 结果：MRR={m['mrr'][0]:.3f}，Recall@10={m[10]['recall'][0]:.3f}，"
            f"Precision@1={m[1]['precision'][0]:.3f}"
            f"（可辩护 {summary['counts']['valid']} 条）"
        )
    else:
        print("[lb] 结果：无可辩护 query，无指标")


if __name__ == "__main__":
    asyncio.run(main())
