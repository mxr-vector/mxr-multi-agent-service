# 一.说明

本项目只涉及推理服务，不涉及模型加载等优化方案。目的是解耦，之间使用http协议。不支持离线服务
- 本地推理框架使用vllm: https://docs.vllm.com.cn/en/latest/getting_started/installation/gpu/#create-a-new-python-environment

本项目涉及多个外部中间件和基础组件的集成。虽然 LangGraph 提供了较丰富的封装能力，但在实际使用过程中发现，其对于部分第三方组件（例如 Cohere 等）的适配能力存在一定局限，因此底层建议使用各自官方客户端，使用兼容层适配框架，因此一般langchain_adapter.py是访问底层客户端的入口。


## 1.1 项目结构


## 1.2 RAG 系统

### 1.2.1 RAG 检索存储方案选择

通用场景下的 RAG（Retrieval-Augmented Generation）方案采用向量数据库作为知识检索基础设施。虽然知识图谱能够表达实体之间的关系，但在通用领域中，由于业务对象类型多样、关系定义复杂，难以提前完成稳定的实体建模和边属性设计，容易导致模型扩展成本较高。

因此，本项目采用向量数据库作为通用 RAG 的核心存储方案，通过语义向量实现知识检索。对于具有明确业务规则和实体关系的垂直领域场景，可在此基础上扩展引入知识图谱能力，实现结构化知识增强。

[向量数据库选型参考](https://zhuanlan.zhihu.com/p/1983908007046846433)
[向量数据库对比 2026: Qdrant vs ChromaDB vs pgvector 选型指南](https://jangwook.net/zh/blog/zh/vector-db-comparison-2026-qdrant-chroma-pgvector/)

# 二.本地推理框架部署

本部署内容和当前项目无关。为了解耦使用web服务协议，避免引入离线llm服务增加项目负担。

先决条件: linux系统

## 2.1 环境部署
```shell
uv venv --python 3.12 --seed --managed-python
source .venv/bin/activate

export UV_HTTP_TIMEOUT=300
# cuda
uv pip install vllm --extra-index-url https://download.pytorch.org/whl/cu128
# rocm
uv pip install vllm --extra-index-url https://wheels.vllm.ai/rocm/ --upgrade
```

## 2.2 快速开始
```shell
# pool model  vllm 0.25.1+
vllm serve ./models/Qwen3-Embedding-0.6B \
    --host 0.0.0.0 \
    --port 8001 \
    --served-model-name Qwen3-Embedding-0.6B \
    --runner pooling \
    --dtype auto \
    --gpu-memory-utilization 0.85 \
    --max-model-len 8192 \
    --max-num-seqs 256 \
    --max-num-batched-tokens 32768 \
    --trust-remote-code \
    --api-key 123456

# chat model
vllm serve Qwen/Qwen3-8B \
    --host 0.0.0.0 \
    --port 8000 \
    --served-model-name Qwen3-8B \
    --dtype auto \
    --gpu-memory-utilization 0.85 \
    --max-model-len 32768 \
    --max-num-seqs 256 \
    --max-num-batched-tokens 32768 \
    --trust-remote-code \
    --api-key 123456
```

# 三.池化模型说明

## 2.1 嵌入模型

经过综合考虑，为降低模型维护成本，避免在不同模块中重复引用模型配置导致版本不一致、向量维度或量化结果不一致等问题，系统不支持在方法层级单独指定嵌入模型。统一通过环境配置文件中的 `EMBEDDING_MODEL_NAME` 参数指定全局使用的嵌入模型，确保系统内所有向量生成流程使用一致的模型配置。

