"""
Rewrite / Compression 模型 client 工厂。

与 model/chat/factory.py 职责区分：chat 模型负责对话与最终答案生成，
本模块的模型专注于问题改写、上下文压缩等辅助性任务，便于独立配置、各司其职。
模型名 / 认证参数由 ENV 决定（REWRITE_MODEL_NAME / REWRITE_API_URL / REWRITE_API_KEY）。
"""

from langchain_openai import ChatOpenAI

from utils.env import ENV


def build_compression_model(temperature: float = 0) -> ChatOpenAI:
    """按 ENV 构造指向 vLLM 的 OpenAI 兼容 rewrite/compression model。

    默认低温度以获得更确定、更贴近原意的改写与压缩结果。
    """
    return ChatOpenAI(
        model=ENV.rewrite_model_name,
        base_url=ENV.rewrite_api_url,
        api_key=ENV.rewrite_api_key,
        temperature=temperature,
    )
