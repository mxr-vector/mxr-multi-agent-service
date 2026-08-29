# RAG 系统

## 1. 先决条件

1. PostgreSQL 18.0+（表结构使用内置 `uuidv7()`，要求 PG ≥ 18）
2. Qdrant@latest 向量库（仅需启动服务；知识库集合由后端首次向量化写入时自动创建，无需手工建集）

```bash
mkdir -p $HOME/mydata/qdrant/storage
# qdrant  http://127.0.0.1:6333/dashboard
podman run -d  \
--name qdrant \
-p 6333:6333  \
-p 6334:6334  \
-v "$HOME/mydata/qdrant/storage:/qdrant/storage:z" \
-e QDRANT__SERVICE__API_KEY=95279527 \
docker.io/qdrant/qdrant
```

3. 模型推理服务（本地 vLLM 部署见 [README.md](../README.md) 二.节，也可使用云端 OpenAI 兼容 API）：
   - 池化模型（embedding + rerank）：如 `Qwen3-Embedding-4B`（`--runner pooling`，默认端口 9527）
   - 生成模型（chat + rewrite）：如 `Qwen3.5-2B`（需 `--enable-auto-tool-choice --tool-call-parser hermes`，默认端口 9528）
   - 显存至少 16G（CUDA/ROCm 均可）
4. 初始化数据库：依次执行 `readme/sql/` 下三个脚本（见 5.1）
5. 配置分两处：postgres/qdrant/embedding 等部署级配置在 `env/.env.development`；
   chat/rewrite/rerank/visual 模型与 RAG 运行参数在数据库，启动后于前端「模型管理 / 参数管理」页维护（免重启热更新）

> **BM25 稀疏通道**：主路径为 jieba 中英双语分词编码器（`model/sparse/bm25.py`，中文 jieba + 英文小写化切词，混合文本自动分流），纯本地实现，**无需下载任何模型**；
> 旧 fastembed `Qdrant/bm25` 降级为 legacy（`legacy_*` 函数），仅供迁移回滚（`utils/migrate_sparse.py`）与对照评测。
> 分词器升级后既有知识库需重算 sparse 向量：`uv run python utils/migrate_sparse.py --kb-id <uuid>`（dense/payload 保留）。

## 2. 检索存储方案选择

- **md-grep** 无法做到近似匹配、语义理解，需要精准意图识别；无法像 rag 做到全文或分块给模型。适用范围有限，适合 代码/API类/概念提要
- **repo wiki** 牺牲全文质量，提升检索效率。有损压缩后的知识总结，可能遗漏约束细节。适合个人知识库、经验笔记总结
- **rag** 海量通用企业级知识库场景。通用场景下的 RAG（Retrieval-Augmented Generation）方案采用向量数据库作为知识检索基础设施。虽然知识图谱能够表达实体之间的关系，但在通用领域中，由于业务对象类型多样、关系定义复杂，难以提前完成稳定的实体建模和边属性设计，容易导致模型扩展成本较高

因此，本项目采用向量数据库作为通用 RAG 的核心存储方案，通过语义向量实现知识检索。对于具有明确业务规则和实体关系的垂直领域场景，可在此基础上扩展引入知识图谱能力，实现结构化知识增强。

[向量数据库选型参考](https://zhuanlan.zhihu.com/p/1983908007046846433)
[向量数据库对比 2026: Qdrant vs ChromaDB vs pgvector 选型指南](https://jangwook.net/zh/blog/zh/vector-db-comparison-2026-qdrant-chroma-pgvector/)
[Qdrant使用手册](https://qdrant.org.cn/documentation/quickstart/)

PostgreSQL 作为关系型知识库持久化维护，也便于经过向量块命中后返回完整文档，交给对话模型；并能根据命中块精准定位来源出处，同时记录了对话消息。

## 3. 系统架构

### 3.1 双库分工

| 存储 | 职责 | 说明 |
|--|--|--|
| PostgreSQL（`rag` schema） | 业务事实源 | 知识库/文件夹/文档/父子块/问答会话与消息全部持久化于此；向量命中后回查完整上下文、章节与页码 |
| Qdrant | 向量检索 | 每知识库一个集合（命名 `kb_{id.hex}_v1`，后端派生，前端无感知），混合集合含 dense + sparse 双命名向量；PG 不存向量 |

表结构见 [readme/sql/rag_schema.sql](./sql/rag_schema.sql)（含典型写入/浏览/检索流程示例）。

### 3.2 父子块模型（Parent-Child / Small-to-Big）

- 两级切分：level 1 父块（2000 字符）→ level 0 叶块（400 字符 / 80 重叠）
- 仅 **level 0 叶块**入 Qdrant（point id = chunk id）；命中后回溯父块/文档，给对话模型更完整的上下文
- 切块策略（上传时可选）：`auto`（有结构走章节，否则回退字符）/ `char` / `structure`（强制章节，仅 markdown/docx/excel）
- 支持 pdf / markdown / excel / docx / text / csv；PDF 回填页码，markdown/docx/excel 回填章节标题
- 增量更新：`content_hash` 判变，重传生成新 `document_version`；向量化后灰度清理旧版本点，避免检索读到"半新半旧"

### 3.3 检索与问答管线（Agentic RAG）

```
提问 → LangGraph respond 节点：对话模型多轮工具循环
     → knowledge_base_search 检索工具：
         混合召回（dense 语义 + jieba BM25 词法，服务端 RRF 融合、去重）
         → 多跳门控（多跳题：实体锚点逐跳检索 + wiki 门控导航 → 合并池）
         → 反思自纠错（结果不足时改写重检索，轮数上限 RAG_REFLECT_ROUND_CAP）
         → rerank 精排裁剪到 RAG_FINAL_TOP_K
     → 模型不再发起工具调用 → 生成答案 + 结构化 sources（章节/页码/相似度）
```

- **检索收敛在工具实现**（`agent/tools/rag_tools.py`，原独立检索子图 `agent/graph/sub/rag_graph.py` 已并入）：混合检索经 `agent/tools/document.py::hybrid_retrieve_multi` 跨库扇出（未选库时自动解析为当前用户可见范围：本人 ∪ 部门 ∪ public）；多跳编排与合并池见 `agent/tools/multihop.py`
- **问答父图**（`agent/graph/chat_graph.py`）：LangGraph 编排，checkpointer（Postgres 池）持久化多轮状态，TTL 后台任务定期清理；业务查询一律走 `rag.chat_sessions/chat_messages` 事实表
- **配置驱动**：候选池 `RAG_CANDIDATE_POOL_SIZE`、最终 top-k `RAG_FINAL_TOP_K`、反思轮数上限 `RAG_REFLECT_ROUND_CAP`、多跳合并池 `RAG_MULTIHOP_MERGE_POOL` 均为 `sys_config` 白名单参数，前端「参数管理」页热更新

### 3.4 权限与配置

- **数据权限**：知识库可见性 `private / department / public` + 用户部门 data_scope，服务端强制收口（不可见与不存在同文案，不泄露存在性）
- **配置双轨**：`EMBEDDING_*` 保留在 env（换模型即毁向量库，部署级钉死）；chat/rewrite/visual/rerank 四角色模型在 `sys.sys_model_config`，经配置快照 `CFG` 读取，写后热更新（校验失败保留旧快照 last-known-good）

## 4. 基准测试

**测试模型与环境**（下表所有行共用；模型配置均在数据库热更新，更换后需重测）：

| 角色 | 模型 / 实现 | 说明 |
|--|--|--|
| 嵌入模型（embedding） | Qwen3-Embedding-4B（vLLM pooling，端口 9527） | `EMBEDDING_*` 部署级钉死，换模型即毁向量库 |
| 重排模型（rerank） | Qwen3-Embedding-4B 双塔（同池化服务） | 与嵌入模型同源同类型 |
| 稀疏通道（BM25） | jieba 中英双语分词编码器（纯本地，无模型下载） | dense + sparse RRF 融合召回 |
| 对话模型（4.1 QA 端到端） | mimo-v2.5（历史锚点）/ glm-5.3-flash（现行） | 仅影响 4.1 节；检索指标不依赖对话模型 |
| 评测语料 | Agriculture Wiki QA + LongBench 五子集（各 200 条） | 独立建库，规模见下表 |

|测试集|规模（建库）|指标口径|Recall@1|Precision@1|Recall@3|Precision@3|Recall@5|Precision@5|Recall@10|Precision@10|NDCG@10|MRR|Hit@10|
|--|--|--|--|--|--|--|--|--|--|--|--|--|--|
|[chal1ce/Agricultrue_Wiki_QA_110K](https://www.modelscope.cn/datasets/chal1ce/Agricultrue_Wiki_QA_110K/dataPeview)|2,919 文档 / 23,953 叶块|严格（chunk 级）|0.357|0.789|0.650|0.566|0.753|0.428|0.753|0.214|0.751|0.826|—|
|[chal1ce/Agricultrue_Wiki_QA_110K](https://www.modelscope.cn/datasets/chal1ce/Agricultrue_Wiki_QA_110K/dataPeview)|2,919 文档 / 23,953 叶块|宽松（文档级）|0.847|0.847|0.904|0.301|0.904|0.181|0.904|0.090|0.882|0.874|—|
|LongBench：dureader（中文，多文档 QA）|200 条 query（独立库 7,362 文档）|native（171/200）|0.126|0.211|0.361|0.205|0.616|0.222|0.990|0.187|0.567|0.437|1.000|
|LongBench：dureader（中文，多文档 QA）|200 条 query（独立库 7,362 文档）|tool（168/200）|0.126|0.208|0.355|0.202|0.612|0.221|0.990|0.187|0.565|0.433|1.000|
|LongBench：2wikimqa（英文，多跳 QA）|200 条 query（独立库 19,900 文档）|native（187/200）|0.024|0.064|0.071|0.071|0.119|0.071|0.213|0.061|0.137|0.170|0.433|
|LongBench：2wikimqa（英文，多跳 QA）|200 条 query（独立库 19,900 文档）|tool（184/200）|0.024|0.065|0.073|0.072|0.121|0.072|0.209|0.060|0.136|0.160|0.418|
|LongBench：musique（英文，多跳 QA）|200 条 query（独立库 37,881 文档）|native（153/200）|0.019|0.065|0.055|0.054|0.079|0.050|0.097|0.041|0.083|0.131|0.242|
|LongBench：musique（英文，多跳 QA）|200 条 query（独立库 37,881 文档）|tool（153/200）|0.026|0.072|0.057|0.057|0.079|0.050|0.098|0.041|0.086|0.124|0.242|
|LongBench：hotpotqa（英文，多跳 QA）|200 条 query（独立库 37,277 文档）|native（189/200）|0.037|0.190|0.101|0.155|0.126|0.128|0.175|0.104|0.181|0.318|0.566|
|LongBench：hotpotqa（英文，多跳 QA）|200 条 query（独立库 37,277 文档）|tool（189/200）|0.038|0.196|0.101|0.155|0.126|0.128|0.176|0.104|0.182|0.308|0.566|
|LongBench：multifieldqa_zh（中文，单文档 QA）|200 条 query（独立库 3,320 文档）|native（65/200）|0.301|0.354|0.538|0.241|0.602|0.163|0.674|0.095|0.522|0.497|0.723|
|LongBench：multifieldqa_zh（中文，单文档 QA）|200 条 query（独立库 3,320 文档）|tool（65/200）|0.301|0.354|0.530|0.236|0.587|0.160|0.671|0.094|0.520|0.486|0.738|

> **口径说明（2026-08-29 复测，以下 LongBench 行均为最新代码结果）**
>
> - **测试模型**：检索指标不依赖对话模型；embedding / rerank 为 Qwen3-Embedding-4B（双塔），BM25 为主路径 jieba 编码器
> - **native**：无 wiki 导航，原问题 → 混合召回（dense + BM25 RRF）→ 候选池 50 → 对原问题统一重排 → top-10；**tool**：`kb_wiki_lookup` 门控导航 → 逐跳多跳检索（生产语义 `multihop-only-multihop`，仅多跳题启用多跳）→ 合并池统一重排
> - **gold 口径**：文档级（answer gold docs，contain 判定），与 Agriculture 行的 chunk 级严格口径不同，两者不可直接对比；括号内 ok/200 为 gold 有效的样本数
> - **Hit@10（新增列）**：top-10 中**至少命中一个 gold 文档**的题占比——与用户体检最对应的检索口径（答对只需一个含答案的文档，不需要 gold 全中）；dureader 达 100%，单文档场景 72-74%
> - **Recall@10 与 Hit@10 的差距**：多跳题平均 2-4 个 gold 文档，Recall 要求全部命中（分数被分母稀释），Hit 只要求中一个——两者都是真实口径，前者用于工程诊断（哪一层丢了 gold），后者用于体验评估（能否支撑答题）
> - **代码状态**：实体扩展通道已移除、分层确定性工具默认关闭（`AGENTIC_TOOLS_ENABLED=false`），两轮均在此形态下测得；多跳检索（hop 查询 + 门控 + 合并池）为检索层内生能力
> - Agriculture 行为历史数据（旧 chunk 级口径），未随本次复测更新
> - Agent 级端到端 QA 口径见 4.1 节

### 4.1 Agent 级端到端多跳 QA 基准（四臂归因，2026-08-29）

以 LongBench 多跳三子集（2wikimqa / hotpotqa / musique 各 200 条）驱动**完整对话图**（检索工具 + respond 工具循环）端到端问答，答案与金标做 contain-match 判定：

| 测试臂 | 对话模型 | 分层确定性工具 | 样本 ok | QA 准确率 | 平均工具轮次 | 平均延迟 |
|--|--|--|--|--|--|--|
| 对照臂（历史锚点） | mimo-v2.5 | ✗ | 600/600 | 34.5% | 2.2 | 38s |
| **对照臂（现行基线）** | glm-5.3-flash | ✗ | 600/600 | **68.3%** | 2.16 | 78s |
| 工具臂（chunk_read 修复前） | glm-5.3-flash | ✓ | 598/600 | 66.9% | 2.43 | 124s |
| 工具臂（修复后复测） | glm-5.3-flash | ✓ | 574/600 | 65.7% | 2.53 | 92s |

**说明**

- **测试模型**：对话模型两档——mimo-v2.5（历史锚点，云端网关）与 glm-5.3-flash（现行 `sys.sys_model_config` chat 角色）；embedding / rerank 全程 Qwen3-Embedding-4B，四臂同配置，检索层结果跨臂可比
- **判定口径**：答案 contain-match 金标（不要求完全相等）；失败 / 超时样本计入分母不剔除

**注意事项**

1. **模型变量主导**：34.5% → 68.3% 的提升全部来自对话模型升级；同模型（glm）下分层确定性工具（`entity_relation_lookup` / `chunk_read`）净贡献 ≈ 0（Δ = −2.6pt，两比例 z 检验 z = −0.97，不显著）
2. **分层工具默认关闭**（`AGENTIC_TOOLS_ENABLED=false`）：净贡献 ≈ 0 且延迟 +18~60%；关系索引资产（32,953 条实体关系）与构建 CLI（`python -m entity_index.build_cli --kb-id <id>`）全部保留，弱模型 / 小上下文场景一行配置开启即用，无需重建索引
3. **口径区别**：本表是 QA 端到端口径（含对话模型生成），与上表检索指标（Recall / NDCG，不含生成）口径不同，不可直接混比
4. 工具臂复测中的 chunk_read 修复（UUID 格式归一 + 知识库作用域）属正确性 / 安全性修复，不改变净效果；修复前该工具因格式缺陷实际不可用（仅 4 次调用）

**复现**：`test/dataset01/eval/longbench_agent_eval.py`（工具臂）/ `--no-agent-tools`（对照臂）；完整归因分析见 [test/dataset01/results/four_arm_attribution_report.md](../test/dataset01/results/four_arm_attribution_report.md)


## 5. 快速开始

### 5.1 初始化数据库

创建数据库后依次执行 `readme/sql/` 下脚本（先建表、后灌种子）：

```bash
psql -U postgres -d multi_agent_db -f readme/sql/system_schema.sql   # sys 系统管理表（用户/角色/菜单/字典/模型配置等）
psql -U postgres -d multi_agent_db -f readme/sql/rag_schema.sql      # rag 业务表（知识库/文件夹/文档/父子块/会话/消息）
psql -U postgres -d multi_agent_db -f readme/sql/base_seed.sql       # 种子：字典/菜单/角色/示例模型配置
```

说明：

- LangGraph checkpoint 表（`checkpoints`/`checkpoint_blobs`/`checkpoint_writes` 等）由
  `langgraph-checkpoint-postgres` 的 setup() 自动创建与演进，无需手工建
- `base_seed.sql` 含示例模型配置与密钥（本地示例值）；生产环境建议部署者线下自行生成
  种子执行并留存作容灾快照

### 5.2 环境变量配置

拷贝 `env/.env.sample` 生成 `env/.env.development`（`APP_ENV` 为 development 时加载），关键项：

| 分组 | 键 | 说明 |
|--|--|--|
| 服务 | `SERVER_HOST` / `SERVER_PORT` / `BASE_URL` / `API_SECRET_KEY` | 服务监听地址与请求鉴权密钥 |
| 认证 | `JWT_SECRET_KEY` / `JWT_EXPIRE_HOURS` | 登录 token（签名密钥与 API_SECRET_KEY 严格分离） |
| PostgreSQL | `POSTGRES_*` | 关系库连接 |
| Qdrant | `QDRANT_HOST` / `QDRANT_PORT` / `QDRANT_API_KEY` / `QDRANT_HTTPS` | 向量库连接（服务端未启用 TLS 时保持 false） |
| embedding | `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL_NAME` / `EMBEDDING_API_URL` / `EMBEDDING_API_KEY` | 全局向量模型；provider 可选 `openai` / `dashscope` / `cohere`（本地 vLLM 走 cohere 协议时 URL 不带 `/v1`），模型名须与 vLLM 实际部署一致 |
| 下载 | `HF_ENDPOINT` / `BM25_CACHE_DIR` | legacy fastembed BM25 模型的下载端点（默认 hf-mirror）与缓存目录（jieba 主路径用不到） |

> 模型配置与运行参数已迁移至数据库（`sys.sys_model_config` / `sys.sys_config`），经配置快照
> `core.config_snapshot.CFG` 读取并支持免重启热更新；env 中不再维护 `CHAT_*` / `REWRITE_*` /
> `RERANK_*` / `RAG_*` 等键（`EMBEDDING_*` 因换模型即毁向量库，保留为部署级钉死项）。

### 5.3 启动服务

后端与前端启动步骤统一见 [README.md](../README.md) 四.启动项目（后端 `uv run python infer.py`；前端 `multi-agent-ui` 目录下 `pnpm install && pnpm dev`，端口 19527）。

### 5.4 配置模型与运行参数

启动后访问前端（登录账号见 `base_seed.sql` 种子用户），在「系统管理 → 模型管理」页
配置四个角色模型（api_url / api_key / 超时 / 重试 / 上下文窗口）：

- `chat`：对话与最终答案生成
- `rewrite`：检索工具内反思自纠错的查询改写（结果不足时改写重检索）
- `rerank`：检索结果精排
- `visual`：多模态（RAG 用不到，Draw 系统使用）

「系统管理 → 参数管理」页配置 RAG 运行参数（默认值见种子，修改即时生效）：

| 参数 | 默认 | 说明 |
|--|--|--|
| `RAG_CANDIDATE_POOL_SIZE` | 50 | 混合召回（dense+sparse RRF 融合）后保留的候选池上限 |
| `RAG_FINAL_TOP_K` | 5 | rerank 精排后保留的最终候选数 |
| `RAG_REFLECT_ROUND_CAP` | 3 | 反思循环最大检索轮数上限 |
| `CHAT_CHECKPOINT_TTL_DAYS` | 7 | checkpoint 保留天数（超期后台任务清理） |
| `CHAT_HISTORY_MAX_MESSAGES` | 20 | 无 checkpoint 历史时回落业务表读取的历史消息条数上限 |

![model_config.png](./assets/images/model_config.png)

### 5.5 使用流程

1. **创建知识库**：「RAG 系统 → AI 知识库管理」，选择归属部门与可见性（private/department/public）
2. **上传文档**：「RAG 系统 → 文档管理」，选择文件夹 / 切块策略 / 有效期后上传；
   上传仅解析 + 切块持久化，需点击**向量化**触发后台异步作业（状态 `reindexing → active/failed`，可轮询）
3. **对话测试**：在「会话中心」选择知识库发起问答（SSE 流式输出，答案附结构化 sources：
   引用序号 / 文档 / 知识库 / 章节 / 页码 / 相似度）

![chat.png](./assets/images/chat.png)

## 6. 常见问题

### 6.1 RAG 效果差?

- **模型类型一致性**：rerank 和 embedding 模型类型须一致，即多模态都是多模态，纯文本都是纯文本
- **召回不足**：候选池 / 反思轮数上限过小会截断召回，可调大 `RAG_CANDIDATE_POOL_SIZE`、`RAG_REFLECT_ROUND_CAP`（参数管理页热更新）
- **文档未向量化**：确认文档状态为 `active`（`failed` 见 6.3）

### 6.2 BM25 需要下载模型吗?

不需要。主路径 jieba 中英双语 BM25（`model/sparse/bm25.py`）为纯本地分词编码，无模型下载；
仅回滚到 legacy fastembed `Qdrant/bm25` 时才需下载（`HF_ENDPOINT` 镜像 + `BM25_CACHE_DIR` 缓存）。

### 6.3 文档向量化失败（failed）?

- 检查 embedding 服务可达性及模型名一致性（`EMBEDDING_API_URL` / `EMBEDDING_MODEL_NAME`）；
  `EMBEDDING_TIMEOUT` / `EMBEDDING_MAX_RETRIES` 控制服务不可达时的快速失败，避免作业长时间挂起
- 服务重启会丢失在途后台作业：启动时残留 `reindexing` 文档自动清扫为 `failed`，重试向量化即可

### 6.4 更换 embedding 模型?

换模型即向量维度 / 语义空间变化，旧向量全部失效：需在 Qdrant 删除对应 `kb_*` 集合后重新向量化
（因此 `EMBEDDING_*` 保持 env 级钉死，避免误改毁库）。

### 6.5 Qdrant 集合在哪里创建?

创建知识库仅落元数据；首次向量化写入时后端自动创建混合集合 `kb_{id.hex}_v1`
（dense + sparse/IDF 双命名向量），可在 `http://127.0.0.1:6333/dashboard` 查看。
