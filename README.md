# 多智能体服务模块


本项目只涉及推理服务，不涉及模型加载等优化方案。目的是解耦，之间使用http协议。不支持离线服务
- 本地推理框架使用vllm: https://docs.vllm.com.cn/en/latest/getting_started/installation/gpu/#create-a-new-python-environment

先决条件: linux系统
```shell
# cuda
uv pip install vllm --torch-backend=auto
# rocm
uv pip install vllm --extra-index-url https://wheels.vllm.ai/rocm/ --upgrade
```