# LongBench v3 wiki-guided evaluation

- dataset: zai-org/LongBench five-subset
- pipeline: kb_wiki_lookup -> multihop knowledge_base_search (per-hop recall/rerank, gated navigation)
- subsets: ['dureader', '2wikimqa', 'musique', 'hotpotqa', 'multifieldqa_zh']
- executed_queries: 1000
- created_at: 2026-08-24T03:50:11.597737+00:00
- wiki_calls: 1000
- queries_with_wiki_hits: 1000
- wiki_hit_rate: 1.0
- navigation_effective_rate: 0.483
- degraded_queries: 0
- timeout_queries: 0
- failed_queries: 0
- avg_hops_executed: 1.198
- avg_online_llm_calls_inside_evidence_tool: 0.0
- avg_latency_ms: 5514.8339000000005

> Derived bridge gold is disclosed separately and is excluded from strict comparison.

## Overall disclosure

| Metric | Value |
|---|---|
| mrr | 0.277±0.345 |
| recall@10 | 0.407±0.445 |
| bridge_recall@10 | 0.242±0.330 |
| hop_success_rate@10 | 0.613±0.398 |
| valid | 765 |

## By question type

| Type | Recall@10 | Bridge Recall@10 | Hop Success Rate@10 |
|---|---|---|---|
| cross-document | 0.989±0.067 | 0.992±0.039 | 1.000±0.000 |
| multi-hop | 0.188±0.307 | 0.137±0.188 | 0.474±0.368 |
| single-hop | 0.658±0.452 | 0.767±0.291 | 0.723±0.451 |
| topic-ambiguous | — | — | — |

## By hop count

| Hops | Recall@10 | Bridge Recall@10 | Hop Success Rate@10 |
|---|---|---|---|
| 1 | 0.852±0.334 | — | 0.888±0.316 |
| 2 | 0.288±0.392 | 0.242±0.330 | 0.540±0.385 |

## Strict annotated comparison

## Strict annotated comparison

| Metric | Value |
|---|---|
| mrr | — |
| recall@10 | — |
| bridge_recall@10 | — |
| hop_success_rate@10 | — |
| valid | 0 |

## Multihop diagnostics

- 分母完整性: executed=1000, ok=1000, timeout=0, failed=0
- 导航有效率: 483/1000 = 48.3%（命中 wiki 且页面含问题实体/成员重合）
- 降级样本: 0（后续跳异常但保留已完成跳候选）
- 平均执行跳数: 1.20

### 逐跳 gold 归因（按跳组计数）

| 阶段 | 跳组数 | 占比 |
|---|---|---|
| 最终 top-10 命中 | 807 | 57.6% |
| 在候选池但被合并/终排丢失 | 328 | 23.4% |
| 逐跳召回均未命中 | 266 | 19.0% |

### 实体扩展通道诊断

- 通道启用: 600/1000（索引可用且开关开启）
- 链接成功率: 557/600 = 92.8%
- 扩展候选进终排: 557/557 = 100.0%
- 扩展贡献: top-10 命中跳组中经由实体扩展的 294/807 = 36.4%
- 失败归因: 不可链接 43 / 链接但无扩展候选 0 / 进终排未被选中 513

### 查询分解通道诊断

- 通道启用: 0/1000（MULTIHOP_DECOMPOSE_ENABLED 开启）

### 标注型两跳验收口径（目标 hop_success@10 = 0.80）

- 样本: 0 条 query（ok 0，非 ok 0 计入分母披露）
- 跳组命中: 0/0（无有效跳组）
- 目标达成: 无法判定
