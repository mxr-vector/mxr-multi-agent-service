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
|
|—— readme 必读内容 （含数据库sql文件）
```

## 1.2 功能模块

- RAG 系统（知识库检索增强）：[RAG.md](readme/RAG.md)
- Draw 系统（AI 绘图）：[DRAW.md](readme/DRAW.md)

# 二.本地VLLM推理框架部署

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
vllm serve ./models/embeddings/Qwen3-Embedding-4B \
    --host 0.0.0.0 \
    --port 9527 \
    --served-model-name Qwen3-Embedding-4B \
    --runner pooling \
    --dtype auto \
    --gpu-memory-utilization 0.35 \
    --max-model-len 4096 \
    --max-num-seqs 4 \
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
    --gpu-memory-utilization 0.65 \
    --max-model-len 8192 \
    --max-num-seqs 2 \
    --max-num-batched-tokens 8192 \
    --trust-remote-code \
    --enable-auto-tool-choice \
    --tool-call-parser hermes \
    --api-key 95279527
```

# 三.池化模型说明

## 3.1 嵌入模型

经过综合考虑，为降低模型维护成本，避免在不同模块中重复引用模型配置导致版本不一致、向量维度或量化结果不一致等问题，系统不支持在方法层级单独指定嵌入模型。统一通过环境配置文件中的 `EMBEDDING_MODEL_NAME` 参数指定全局使用的嵌入模型，确保系统内所有向量生成流程使用一致的模型配置。

# 其他问题

## 1. cohere运行报错?

本地vllm兼容cohere，但对其做了简化，对部分参数有变化。详见 model\embeddings\clients\cohere.py 说明。当然本项目默认对接本地vllm兼容接口。
