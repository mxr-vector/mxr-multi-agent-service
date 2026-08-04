# dataset01：农业维基 QA 110K — RAG 检索质量评测

用 [chal1ce/Agricultrue_Wiki_QA_110K](https://www.modelscope.cn/datasets/chal1ce/Agricultrue_Wiki_QA_110K)
（农业维基推理问答数据集）对本项目 RAG 系统做检索质量评测，产出
**Recall@K / Precision@K / MRR** 基线。

## 数据

- 文件：`data/agriculture_wiki_qa_full.csv`（约 566MB，train 单份）
- 来源：ModelScope `chal1ce/Agricultrue_Wiki_QA_110K`（Apache-2.0），
  HuggingFace 镜像 `Chal1ce/agricultrue_wiki_reasoning_QA_110K`
- 字段：`pageid / title / question / thinking / answer / content / url`
  - `content` 为维基原文按句切分的证据片段（问题生成的依据）→ **严格 gold**；
  - `pageid / title` 标识来源页面 → **宽松 gold**（页面级）；
  - `question` 为查询；`thinking / answer` 仅佐证，检索评测不使用。
- 下载方式（任选其一）：
  ```bash
  # 方式一：ModelScope 下载 API（匿名可用）
  curl -L -o data/agriculture_wiki_qa_full.csv \
    "https://modelscope.cn/api/v1/datasets/chal1ce/Agricultrue_Wiki_QA_110K/repo?Revision=master&FilePath=agriculture_wiki_qa_full.csv"
  # 方式二：modelscope SDK
  # uv run python -c "from modelscope import snapshot_download; snapshot_download('chal1ce/Agricultrue_Wiki_QA_110K', local_dir='data/')"
  ```
  下载后把 sha256 记录到 `gold/corpus_stats.json`（`build_corpus.py --stats-only` 或首次建库自动写入）。

## 前置依赖（评测前必须就绪）

| 依赖 | 说明 |
|---|---|
| PostgreSQL | 已初始化 schema（`database/sql/base_seed.sql` + `rag_schema.sql`），`sys.sys_model_config` 四行（chat/rewrite/visual/rerank）与 `sys.sys_config` 标量参数齐备（`CFG.load_blocking()` fail-fast） |
| `env/.env.development` | 复制自 `env/.env.sample` 并填写 `EMBEDDING_PROVIDER / EMBEDDING_MODEL_NAME / EMBEDDING_API_URL`、PG/Qdrant 连接 |
| Qdrant | 在线（dense + sparse 混合集合自动创建） |
| embedding 服务 | 在线（建库向量化 + 查询向量化） |
| rewrite / rerank 服务 | 仅完整子图口径需要（`run_queries.py` 的 B 管线）；纯检索口径不需要 |

## 四阶段运行顺序

```bash
cd <项目根>
uv run python test/dataset01/eval/build_corpus.py   # S1 建库（聚合 → 切块 → 入库 → 向量化）
uv run python test/dataset01/eval/build_gold.py     # S2 gold 基准表 + 分层抽样 1000 条
uv run python test/dataset01/eval/run_queries.py    # S3 双管线查询执行（限流并发 4）
uv run python test/dataset01/eval/report.py         # S4 指标计算 + Markdown 报告
```

- S1 可 `--cleanup` 整体删除评测知识库（Qdrant 集合 + PG 数据）后重跑；
- S2/S3/S4 均为可断点续跑（产物落盘后重复执行直接复用/覆盖）；
- 冒烟：S1 支持 `--smoke` 抽样验证召回；S4 支持 `--max-queries N` 小样本先行。

## 指标口径

- **Recall@K** = |gold ∩ topK| / |gold|；**Precision@K** = |gold ∩ topK| / K；
  **MRR** = 1 / 首个 gold 命中位置（无命中记 0）
- K ∈ {1, 3, 5, 10, `RAG_FINAL_TOP_K` 配置值}，纯检索管线取候选池排序前 K，
  完整子图管线取 `reranked_docs` 前 K
- **双口径**：严格（chunk 级：叶块文本规范化后包含该条 `content`）与
  宽松（文档级：同 `pageid` 的任意叶块）；严格口径下 gold 为空的 query 不计入
  指标（单独统计"空占比"）
- **双管线**：A = `hybrid_retrieve_multi`（dense+sparse RRF，无反思无重排）；
  B = `rag_graph` 完整子图（反思多轮 + rerank 后 top-k）
- 汇总：宏平均 mean ± std；报告含 MRR=0 失败案例抽样（每口径 3 条）
