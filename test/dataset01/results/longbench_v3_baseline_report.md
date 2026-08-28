# LongBench v3 no-wiki baseline

- dataset: zai-org/LongBench five-subset current pipeline
- pipeline: no-wiki hybrid retrieval + rerank
- subsets: ['dureader', '2wikimqa', 'musique', 'hotpotqa', 'multifieldqa_zh']
- pool_size: 50
- executed_queries: 1000
- created_at: 2026-08-28T17:08:07.002745+00:00

> Derived bridge gold is disclosed separately and is excluded from strict comparison.

## Overall disclosure

| Metric | Value |
|---|---|
| mrr | 0.286±0.341 |
| recall@10 | 0.393±0.441 |
| bridge_recall@10 | 0.226±0.330 |
| hop_success_rate@10 | 0.597±0.401 |
| valid | 765 |

## By question type

| Type | Recall@10 | Bridge Recall@10 | Hop Success Rate@10 |
|---|---|---|---|
| cross-document | 0.990±0.064 | 1.000±0.000 | 1.000±0.000 |
| multi-hop | 0.166±0.281 | 0.118±0.172 | 0.451±0.363 |
| single-hop | 0.674±0.446 | 0.767±0.291 | 0.723±0.451 |
| topic-ambiguous | — | — | — |

## By hop count

| Hops | Recall@10 | Bridge Recall@10 | Hop Success Rate@10 |
|---|---|---|---|
| 1 | 0.860±0.327 | — | 0.888±0.316 |
| 2 | 0.269±0.380 | 0.226±0.330 | 0.519±0.385 |

## Strict annotated comparison

## Strict annotated comparison

| Metric | Value |
|---|---|
| mrr | — |
| recall@10 | — |
| bridge_recall@10 | — |
| hop_success_rate@10 | — |
| valid | 0 |
