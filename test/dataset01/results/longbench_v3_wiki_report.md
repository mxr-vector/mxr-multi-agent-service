# LongBench v3 wiki-guided evaluation

- dataset: zai-org/LongBench five-subset
- pipeline: kb_wiki_lookup -> multihop knowledge_base_search (per-hop recall/rerank, gated navigation)
- subsets: ['dureader', '2wikimqa', 'musique', 'hotpotqa', 'multifieldqa_zh']
- executed_queries: 1000
- created_at: 2026-08-28T18:07:46.759132+00:00
- wiki_calls: 991
- queries_with_wiki_hits: 984
- wiki_hit_rate: 0.992936427850656
- navigation_effective_rate: 0.4867886178861789
- degraded_queries: 4
- timeout_queries: 2
- failed_queries: 7
- avg_hops_executed: 1.1987891019172554
- avg_online_llm_calls_inside_evidence_tool: 0.0
- avg_latency_ms: 13143.846215943491

> Derived bridge gold is disclosed separately and is excluded from strict comparison.

## Overall disclosure

| Metric | Value |
|---|---|
| mrr | 0.278±0.349 |
| recall@10 | 0.390±0.441 |
| bridge_recall@10 | 0.224±0.327 |
| hop_success_rate@10 | 0.596±0.402 |
| valid | 759 |

## By question type

| Type | Recall@10 | Bridge Recall@10 | Hop Success Rate@10 |
|---|---|---|---|
| cross-document | 0.990±0.065 | 0.992±0.039 | 1.000±0.000 |
| multi-hop | 0.164±0.281 | 0.118±0.172 | 0.450±0.365 |
| single-hop | 0.671±0.445 | 0.767±0.291 | 0.738±0.443 |
| topic-ambiguous | — | — | — |

## By hop count

| Hops | Recall@10 | Bridge Recall@10 | Hop Success Rate@10 |
|---|---|---|---|
| 1 | 0.857±0.329 | — | 0.893±0.310 |
| 2 | 0.267±0.380 | 0.224±0.327 | 0.517±0.387 |

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

- 分母完整性: executed=1000, ok=991, timeout=2, failed=7
- 导航有效率: 479/984 = 48.7%（命中 wiki 且页面含问题实体/成员重合）
- 降级样本: 4（后续跳异常但保留已完成跳候选）
- 平均执行跳数: 1.20

### 逐跳 gold 归因（按跳组计数）

| 阶段 | 跳组数 | 占比 |
|---|---|---|
| 最终 top-10 命中 | 771 | 55.4% |
| 在候选池但被合并/终排丢失 | 342 | 24.6% |
| 逐跳召回均未命中 | 278 | 20.0% |

### 实体扩展通道

- 已移除（评测证伪后删除；桥接证据改由 agent 经 entity_relation_lookup 消费）

### 标注型两跳验收口径（目标 hop_success@10 = 0.80）

- 样本: 0 条 query（ok 0，非 ok 0 计入分母披露）
- 跳组命中: 0/0（无有效跳组）
- 目标达成: 无法判定
