# LongBench 生产工具级评测报告（对齐生产 Agentic 工具调用）

- 生成时间：2026-08-14T10:09:03.310221+00:00
- 评测知识库：各子集独立库（dureader=019ffdec, 2wikimqa=019ffdec, musique=019ffdec, hotpotqa=019ffdec, multifieldqa_zh=019ffdec）（candidate_pool=50，rerank=on）
- 执行 query：1000 条（有效 636 / gold 为空 234 / 失败 130）
- dataset：zai-org/LongBench 多语言（dureader/2wikimqa/musique/hotpotqa/multifieldqa_zh）
- pipeline：生产工具级 knowledge_base_search_impl（混合召回 + 反思改写重检 cap=3 + rerank top_k=10）
- subsets：['dureader', '2wikimqa', 'musique', 'hotpotqa', 'multifieldqa_zh']
- executed_queries：1000

## 文档级指标（gold = qrels/可辩护证据 → document_id，mode=doc）

| K | Recall@K | Precision@K | NDCG@K |
|---|---|---|---|
| 1 | 0.091±0.244 | 0.176±0.381 | 0.176±0.381 |
| 3 | 0.209±0.340 | 0.144±0.211 | 0.206±0.314 |
| 5 | 0.299±0.381 | 0.124±0.152 | 0.237±0.305 |
| 10 | 0.440±0.438 | 0.096±0.104 | 0.292±0.307 |
| MRR | 0.299±0.362 | — | — |

有效 query 数：636

- 可辩护 query：636/1000（answer 可定位到 context 段落）；不可辩护统计：{'answer_not_in_context': 163, 'answer_too_ambiguous': 97}
- 工具统计：平均反思轮数 1.62，平均耗时 28669 ms/条

> 口径限定：本评测调用生产 knowledge_base_search 工具完整实现（混合召回 +反思充分性判定 + 改写查询重检 + rerank 裁剪 top_k=10），与检索层下界（dual，单轮混合召回 + rerank，见 longbench_dual_report.md）区分：本口径额外覆盖工具内反思改写重检；LLM 是否检索、逐跳拆解等 Agentic 外层决策仍不在范围内。gold 口径同 v2 可辩护证据映射，局限见 RAG.md 4.2 节。

## 按子集拆分（中英文 / 任务类型标注）

### dureader（中文，多文档 QA）

- 执行 query：200 条（有效 142 / gold 为空 20 / 失败 38）
- 不可辩护统计：{'answer_not_in_context': 26}

| K | Recall@K | Precision@K | NDCG@K |
|---|---|---|---|
| 1 | 0.056±0.180 | 0.113±0.317 | 0.113±0.317 |
| 3 | 0.238±0.354 | 0.148±0.208 | 0.188±0.279 |
| 5 | 0.496±0.397 | 0.187±0.160 | 0.311±0.269 |
| 10 | 0.937±0.200 | 0.188±0.102 | 0.487±0.194 |
| MRR | 0.330±0.264 | — | — |

### 2wikimqa（英文，多跳 QA）

- 执行 query：200 条（有效 163 / gold 为空 20 / 失败 17）
- 不可辩护统计：{'answer_too_ambiguous': 10, 'answer_not_in_context': 11}

| K | Recall@K | Precision@K | NDCG@K |
|---|---|---|---|
| 1 | 0.052±0.140 | 0.160±0.367 | 0.160±0.367 |
| 3 | 0.174±0.264 | 0.162±0.235 | 0.190±0.274 |
| 5 | 0.228±0.303 | 0.123±0.158 | 0.197±0.251 |
| 10 | 0.267±0.331 | 0.074±0.088 | 0.211±0.255 |
| MRR | 0.285±0.362 | — | — |

### musique（英文，多跳 QA）

- 执行 query：200 条（有效 112 / gold 为空 27 / 失败 61）
- 不可辩护统计：{'answer_too_ambiguous': 32, 'answer_not_in_context': 8}

| K | Recall@K | Precision@K | NDCG@K |
|---|---|---|---|
| 1 | 0.038±0.148 | 0.107±0.311 | 0.107±0.311 |
| 3 | 0.067±0.188 | 0.065±0.154 | 0.087±0.216 |
| 5 | 0.080±0.204 | 0.046±0.104 | 0.084±0.201 |
| 10 | 0.126±0.259 | 0.036±0.068 | 0.099±0.205 |
| MRR | 0.145±0.316 | — | — |

### hotpotqa（英文，多跳 QA）

- 执行 query：200 条（有效 131 / gold 为空 63 / 失败 6）
- 不可辩护统计：{'answer_too_ambiguous': 55, 'answer_not_in_context': 10}

| K | Recall@K | Precision@K | NDCG@K |
|---|---|---|---|
| 1 | 0.077±0.211 | 0.198±0.400 | 0.198±0.400 |
| 3 | 0.154±0.282 | 0.132±0.188 | 0.185±0.284 |
| 5 | 0.191±0.300 | 0.107±0.139 | 0.187±0.268 |
| 10 | 0.254±0.332 | 0.076±0.097 | 0.207±0.267 |
| MRR | 0.296±0.387 | — | — |

### multifieldqa_zh（中文，单文档 QA）

- 执行 query：200 条（有效 88 / gold 为空 104 / 失败 8）
- 不可辩护统计：{'answer_not_in_context': 108}

| K | Recall@K | Precision@K | NDCG@K |
|---|---|---|---|
| 1 | 0.306±0.442 | 0.364±0.484 | 0.364±0.484 |
| 3 | 0.493±0.481 | 0.220±0.231 | 0.446±0.442 |
| 5 | 0.548±0.482 | 0.150±0.152 | 0.464±0.433 |
| 10 | 0.637±0.456 | 0.092±0.086 | 0.498±0.412 |
| MRR | 0.473±0.429 | — | — |
