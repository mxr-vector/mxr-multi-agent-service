# 一.说明

本项目只涉及推理服务，不涉及模型加载等优化方案。目的是解耦，之间使用http协议。不支持离线服务
- 本地推理框架使用vllm: https://docs.vllm.com.cn/en/latest/getting_started/installation/gpu/#create-a-new-python-environment


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

嵌入模型经过考虑，为避免维护负担，多处模型引用不一致，造成量化不一致问题，不支持方法层指定模型，改为在环境文件EMBEDDING_MODEL_NAME 统一指定 .