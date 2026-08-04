# 一.说明

本项目只涉及推理服务，不涉及模型加载等优化方案。目的是解耦，之间使用http协议。不支持离线服务

本地推理框架使用vllm: <https://docs.vllm.com.cn/en/latest/getting_started/installation/gpu/#create-a-new-python-environment>

本项目涉及多个外部中间件和基础组件的集成。虽然 LangGraph 提供了较丰富的封装能力，但在实际使用过程中发现，其对于部分第三方组件（例如 Cohere 等）的适配能力存在一定局限，因此底层建议使用各自官方客户端，使用兼容层适配框架，因此一般langchain_adapter.py是访问底层客户端的入口。

host设置

```bash
# macos/linux
# 将 env/host.txt 的内容逐行添加到 /etc/hosts 文件中
cat env/host.txt >> /etc/hosts

# window
type env\host.txt >> C:\Windows\System32\drivers\etc\hosts
```

|功能实现|状态|
|--|--|
|RAG系统|- [:heavy_check_mark:]|
|AI剧本生成|- [:x:]|
|AI图像转写手绘|- [:smile:]|

## 1.1 项目结构

```text
project
|—— env # 开发生产环境目录 (需要.env.sample 复制到 .env.development,.env.production下)
|
|—— core # 核心配置目录(数据库连接，自动导包等)
|
|—— database # 数据库的crud操作 
|
|—— exception # 全局异常/自定义异常
|
|—— middleware # web访问层中间件
|
|—— routers # web路由入口
|
|—— static # 服务门户页面
|
|—— model # 存放各类模型客户端，提供抽象层方法
|     |-- chat # 文本类模块
|     |-- embeddings # 嵌入向量模型
|     |-- rerank # 重排序模型
| 
|—— utils # 常规辅助工具类
| 
|—— agent # 智能体代理模块
|     |-- prompts # 提示词维护模块
|     |-- tools # 智能体调用工具模块
|     |-- sub # 子智能体模块 （不同场景）
| 
|—— multi-agent-ui # 简单的前端测试项目(Vue3.x)
```

## 1.2 RAG 系统

|测试集|Recall@K(召回率)|Precision@K(准确率)|MRR(算术平均首位度)|
|--|--|--|--|
|[chal1ce/Agricultrue_Wiki_QA_110K](https://www.modelscope.cn/datasets/chal1ce/Agricultrue_Wiki_QA_110K/dataPeview)||||
|[C-MTEB/T2Retrieval](https://huggingface.co/datasets/C-MTEB/T2Retrieval)||||
|[zai-org/LongBench](https://huggingface.co/datasets/zai-org/LongBench)||||

|功能|测试模型|
|--|--- |
| embedding | Qwen3-Embedding-4B |
| rerank | Qwen3-Embedding-4B |
| chat | DeepSeek-V4-Flash-high |
| rewrite | Step-3.7-flash |
| bm2.5 | qdrant-bm2.5 |

### 1.2.1 先决条件

1. PostgreSQL 18.0+
2. Qdrant@latest 向量库

```bash
# qdrant  http://127.0.0.1:6333/dashboard
podman run -d  \
--name qdrant \
-p 6333:6333  \
-p 6334:6334  \
-v qdrant_storage:$HOME/mydata/qdrant/storage \
-e QDRANT__SERVICE__API_KEY=95279527 \
docker.io/qdrant/qdrant
```

1. Rocm/CUDA 显卡 16G(显存至少满足16G)
2. 内嵌自动下载 qdrant-bm2.5/rapidocr模型  （辅助bm2.5 检索）
3. 本地分别配置  postgres,qdrant，embedding,rerank,chat,rewrite 模型api

### 1.2.2 RAG 检索存储方案选择

- md-grep 无法做到 近似匹配，语义理解，需要精准意图识别，无法像rag做到全文或分块给模型。适用范围有限，适合 代码/API类/概念提要
- repo wiki 牺牲全文质量，提升检索效率。有损压缩后的知识总结，可能遗漏约束细节。适合个人知识库，经验笔记总结。
- rag 海量通用企业级知识库场景。 通用场景下的 RAG（Retrieval-Augmented Generation）方案采用向量数据库作为知识检索基础设施。虽然知识图谱能够表达实体之间的关系，但在通用领域中，由于业务对象类型多样、关系定义复杂，难以提前完成稳定的实体建模和边属性设计，容易导致模型扩展成本较高。

因此，本项目采用向量数据库作为通用 RAG 的核心存储方案，通过语义向量实现知识检索。对于具有明确业务规则和实体关系的垂直领域场景，可在此基础上扩展引入知识图谱能力，实现结构化知识增强。

[向量数据库选型参考](https://zhuanlan.zhihu.com/p/1983908007046846433)
[向量数据库对比 2026: Qdrant vs ChromaDB vs pgvector 选型指南](https://jangwook.net/zh/blog/zh/vector-db-comparison-2026-qdrant-chroma-pgvector/)

[Qdrant使用手册](https://qdrant.org.cn/documentation/quickstart/)

PostgreSQL作为关系型知识库持久化维护，也便于经过向量块命中后返回完整文档，交给对话模型。并能根据命中块精准定位来源出处。也记录了对话消息。

## 1.3 Draw 系统

### 1.3.1 先决条件

1. 配置 VISUAL_* 多模态模型（VISUAL_MODEL_NAME / VISUAL_API_URL / VISUAL_API_KEY，需支持 vision，如 step-3.7-flash）
2. 部署 drawio 并配置

```bash
podman run -d \
  --name drawio \
  --restart unless-stopped \
  -p 8080:8080 \
  jgraph/drawio
```

1. drawio 实例地址由后端运行参数 `DRAWIO_EMBED_URL` 提供（`sys.sys_config` 白名单参数，种子见 `database/sql/base_seed.sql`，可在前端模型配置页「运行参数」中修改；如 `http://localhost:8080`，同时作为 postMessage origin 校验基准）
2. 执行绘图模块建表：`database/draw_schema.sql`（draw schema 下会话/消息/图表版本三表）
3. 系统菜单已内置 AI 绘图菜单（`database/system_schema.sql` 种子，component 键 `draw`）；需为对应角色授权可见

### 1.3.2 设计要点

- 多模态模型仅输出 Mermaid：前端 mermaid.js 实时预览；点击「在 drawio 中编辑」经 embed 模式（`descriptor:{format:'mermaid',wrap:true}`）载入编辑器
- 图表版本链 append-only：AI 生成与 drawio 编辑保存均产生新版本（`parent_id` 指向基线），不覆盖旧版本
- export-server 为二期能力：一期预览由前端编辑器 `export xmlpng` 产出（内嵌 XML 的 PNG，单文件既是预览又可重载编辑）

# 二.本地推理框架部署

本部署内容和当前项目无关。为了解耦使用web服务协议，避免引入离线llm服务增加项目负担。

先决条件: linux系统

## 2.1 环境部署

```shell
uv venv --python 3.12 --seed --managed-python
source .venv/bin/activate

export UV_HTTP_TIMEOUT=300
# cuda
uv pip install vllm --extra-index-url https://download.pytorch.org/whl/cu130
# rocm
uv pip install vllm --extra-index-url https://wheels.vllm.ai/rocm/ --upgrade
```

## 2.2 运行vllm服务

```shell
# pool model  vllm 0.25.1+
vllm serve ./models/embeddings/Qwen3-Embedding-0.6B \
    --host 0.0.0.0 \
    --port 9527 \
    --served-model-name Qwen3-Embedding-0.6B \
    --runner pooling \
    --dtype auto \
    --gpu-memory-utilization 0.25 \
    --max-model-len 2048 \
    --max-num-seqs 8 \
    --max-num-batched-tokens 8192 \
    --trust-remote-code \
    --api-key 95279527 

# compress model  可以使用 cloud 兼容openai接口
# 关于 工具调用 https://docs.vllm.com.cn/en/latest/features/tool_calling/
# --tool-call-parser hermes  or --tool-call-parser openai

vllm serve ./models/chat/Qwen3.5-2B \
    --host 0.0.0.0 \
    --port 9528 \
    --served-model-name Qwen3.5-2B \
    --dtype half \
    --gpu-memory-utilization 0.75 \
    --max-model-len 8192 \
    --max-num-seqs 2 \
    --max-num-batched-tokens 8192 \
    --trust-remote-code \
    --enable-auto-tool-choice \
    --tool-call-parser hermes \
    --api-key 95279527
```

# 三.池化模型说明

## 2.1 嵌入模型

经过综合考虑，为降低模型维护成本，避免在不同模块中重复引用模型配置导致版本不一致、向量维度或量化结果不一致等问题，系统不支持在方法层级单独指定嵌入模型。统一通过环境配置文件中的 `EMBEDDING_MODEL_NAME` 参数指定全局使用的嵌入模型，确保系统内所有向量生成流程使用一致的模型配置。

# 其他问题

## 1. cohere运行报错?

本地vllm兼容cohere，但对其做了简化，对部分参数有变化。详见 model\embeddings\clients\cohere.py 说明。当然本项目默认对接本地vllm兼容接口。

## 2. RAG效果差?

注意 rerank和 embedding 模型类型一致，即多模态都是多模态，纯文本都是纯文本.
