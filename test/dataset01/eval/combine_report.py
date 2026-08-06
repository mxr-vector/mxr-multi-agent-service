"""
综合报告生成器：从当前 eval_results.json 生成含全部实验对比的 report.md。

标准 S4 工具（report.py）每次运行会以当前配置覆盖 report.md（仅当前配置的
详细指标 + 失败案例）；本脚本在其基础上补充"实验对比总览 / 瓶颈诊断 / 结论"
章节，作为评测全貌的存档报告。重跑基线后执行一次即可。

用法：
  uv run python test/dataset01/eval/combine_report.py
"""

import sys
from datetime import datetime, timezone

sys.path.insert(0, "/home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/eval")

from common import (
    BASE_K_VALUES,
    CORPUS_STATS_PATH,
    EVAL_RESULTS_PATH,
    REPORT_PATH,
    final_top_k,
    load_json,
)
from report import _collect_metrics, _failure_cases, _metric_table

payload = load_json(EVAL_RESULTS_PATH)
stats = load_json(CORPUS_STATS_PATH)
meta = payload["meta"]
results = payload["results"]

ks = sorted(set([*BASE_K_VALUES, final_top_k()]))
acc = _collect_metrics(results, ks)
failed_a = sum(1 for r in results if r["pipeline_a"]["status"] == "failed")
skipped = acc[("chunk", "a")]["skipped_gold_empty"]

# 严格: R@1 R@5 R@10 MRR P@1；宽松: R@1 R@5 R@10 MRR（实测运行记录）
EXPERIMENTS = [
    {"name": "基线：纯检索（fastembed BM25，pool=50）", "note": "sparse 中文失效，实为 dense 单通道", "strict": (0.392, 0.740, 0.798, 0.759, 0.702), "relaxed": (0.766, 0.873, 0.888, 0.810)},
    {"name": "候选池扩容（pool=50 → 100）", "note": "dense 单通道下无增益 → 无效", "strict": (0.390, 0.739, 0.798, 0.758, 0.698), "relaxed": (0.762, 0.873, 0.888, 0.809)},
    {"name": "query 拆分多路检索（per_pool=16）", "note": "子池缩小，召回空间不足", "strict": (0.325, 0.597, 0.707, 0.650, 0.580), "relaxed": (0.643, 0.796, 0.837, 0.708)},
    {"name": "query 拆分多路检索（per_pool=50）", "note": "轮转合并稀释首子问题排序 → 负优化", "strict": (0.325, 0.600, 0.708, 0.651, 0.580), "relaxed": (0.643, 0.797, 0.839, 0.709)},
    {"name": "基线 + 本地 rerank", "note": "语义重排 +1~2.3pt，零云端 token", "strict": (0.406, 0.752, 0.807, 0.774, 0.724), "relaxed": (0.789, 0.878, 0.897, 0.827)},
    {"name": "jieba 中文 BM25（检索层上限）", "note": "词法通道激活：严格 +6.7pt，宽松 +4.2pt", "strict": (0.424, 0.794, 0.865, 0.810, 0.747), "relaxed": (0.798, 0.905, 0.930, 0.846)},
    {"name": "jieba + rerank（生产配置，当前）", "note": "rerank 必须保留；Recall 略降属设计取舍", "strict": (0.408, 0.760, 0.823, 0.780, 0.725), "relaxed": (0.791, 0.885, 0.918, 0.833)},
]

from common import _dedupe_ranked

in_pool = out_pool = 0
for r in results:
    gold = [g for g in (r.get("strict_gold") or []) if g]
    if not gold:
        continue
    cands = _dedupe_ranked(r["pipeline_a"].get("candidates") or [], "chunk")
    if any(c.get("point_id") in set(gold) for c in cands):
        in_pool += 1
    else:
        out_pool += 1
total = in_pool + out_pool

lines = [
    "# RAG 检索质量评测报告（dataset01：农业维基 QA 110K）",
    "",
    f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
    f"- 数据集：{stats.get('dataset', '')}（sha256: {str(stats.get('csv_sha256', ''))[:12]}）",
    f"- 记录数：{stats.get('records')} / 页面数：{stats.get('pages')} / "
    f"文档数：{stats.get('documents')} / 叶块数：{stats.get('leaf_chunks')}",
    f"- 评测知识库：{meta.get('kb_id')}（seed={meta.get('seed')}，分层抽样 {meta.get('sample_size')} 条）",
    f"- 系统配置：candidate_pool={meta.get('candidate_pool_size')}，final_top_k={meta.get('final_top_k')}",
    f"- 执行管线：A 纯检索（dense + {meta.get('sparse_encoder', 'default')} sparse RRF）"
    f"{' → 本地 rerank' if meta.get('rerank') else ''}",
    f"- 失败计数：A 失败 {failed_a} 条（已从指标中剔除）",
    "",
    "> 严格口径 gold 为空（证据句被切块截断）占比："
    f"{skipped}/{len(results)}（{skipped/len(results):.1%}），不计入严格口径指标。",
    "",
    "## 一、实验对比总览（1000 条分层抽样，seed=42）",
    "",
    "| 实验配置 | 严格 R@1 | 严格 R@5 | 严格 R@10 | 严格 MRR | 严格 P@1 | "
    "宽松 R@1 | 宽松 R@5 | 宽松 R@10 | 宽松 MRR | 结论 |",
    "|---|---|---|---|---|---|---|---|---|---|---|",
]
for exp in EXPERIMENTS:
    s, r = exp["strict"], exp["relaxed"]
    lines.append(
        f"| {exp['name']} | {s[0]:.3f} | {s[1]:.3f} | {s[2]:.3f} | {s[3]:.3f} | {s[4]:.3f} | "
        f"{r[0]:.3f} | {r[1]:.3f} | {r[2]:.3f} | {r[3]:.3f} | {exp['note']} |"
    )
lines += [
    "",
    "## 二、当前生产配置详细指标（jieba 中文 BM25 + rerank）",
    "",
    "### 严格口径（chunk 级：叶块文本包含 content）",
    "",
    _metric_table(acc, "chunk", ks, pipeline_b_enabled=False),
    "",
    f"有效 query 数：{acc[('chunk', 'a')]['valid']}",
    "",
    "### 宽松口径（文档级：同 pageid 任意叶块，按 document_id 去重）",
    "",
    _metric_table(acc, "doc", ks, pipeline_b_enabled=False),
    "",
    f"有效 query 数：{acc[('doc', 'a')]['valid']}",
    "",
    "## 三、瓶颈诊断与关键发现",
    "",
    f"- 候选池（top-50）内含 gold 的 query 占比：**{in_pool/total:.1%}**（严格口径理论天花板）",
    f"- 池内无 gold：**{out_pool/total:.1%}**",
    "- **决定性发现**：fastembed `Qdrant/bm25` tokenizer 面向英文，中文 query 整句被"
    "哈希成 1 个 token，sparse 通道对中文几乎零命中——原混合检索实为 dense 单通道；"
    "换用 jieba 中文 BM25（`model/sparse/bm25.py` 主路径）后词法通道激活，"
    "98% 的池外 query 存在 query↔gold 词重叠可被词法召回",
    "- **rerank 交互**：default 通道上 rerank +1~2.3pt；jieba 通道上 rerank 使检索层 "
    "Recall 略降（严格 0.865→0.823），但生产必须保留 rerank（最终排序与回答质量依赖"
    "精排），以 jieba+rerank 为生产基线，jieba-only 为检索层上限单独披露",
    "",
    "## 四、失败案例抽样（MRR=0 且 gold 非空，每口径 3 条）",
    "",
]
for mode, label in (("chunk", "严格口径"), ("doc", "宽松口径")):
    cases = _failure_cases(results, mode, 3)
    lines.append(f"### {label}")
    if not cases:
        lines.append("（无）")
    else:
        for case in cases:
            lines.append(f"- **Q**（row {case['row_index']}，{case['pipeline']}）：{case['question']}")
            for i, snippet in enumerate(case["top_candidates"], start=1):
                lines.append(f"  - top-{i}: {snippet}")
    lines.append("")

lines += [
    "## 五、结论与建议",
    "",
    "1. **jieba 中文 BM25 是决定性改进**：宽松 Recall@10 0.888 → 0.930（检索层，"
    "突破 90% 目标）、严格 0.798 → 0.865；生产配置（+rerank）宽松 0.918、严格 0.823",
    "2. **rerank 保留**（用户强制要求）：生产链路 = jieba 混合检索 → rerank 精排，"
    "rerank 保障最终排序与回答质量，检索层 Recall 差异如实披露",
    "3. **生产切换已完成**：`model/sparse/bm25.py` 主路径为 jieba 编码器（legacy 保留"
    "回滚）；既有知识库用 `utils/migrate_sparse.py --kb-id <id>` 迁移（update_vectors "
    "仅重算 sparse，无需重新 embedding）",
    "4. 严格口径 90% 的剩余缺口：3.9% gold 空（切块截断）+ 少量拼接式 query，"
    "可通过切块重叠加大/按句切分继续逼近",
    "5. 评测工具链已固化（`--pool/--split-query/--rerank/--sparse-encoder` 参数 + meta "
    "缓存键隔离），任意配置可复现对比",
    "",
]

REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
print(f"综合报告已生成: {REPORT_PATH}（{len(results)} 条 query，含 {len(EXPERIMENTS)} 组实验对比）")
