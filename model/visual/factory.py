"""
Visual 多模态模型 client 工厂。

统一封装指向 OpenAI 兼容接口（需支持 vision）的多模态 chat model 构造逻辑，
绘图模块通过 build_visual_model() 获取模型实例；模型名与端点由 ENV 决定
（VISUAL_MODEL_NAME / VISUAL_API_URL / VISUAL_API_KEY），与 chat/rewrite
模型各司其职（对齐 model/chat/factory.py 的工厂约定）。
"""

from langchain_openai import ChatOpenAI

from utils.env import ENV


def build_visual_model(temperature: float = 0.2) -> ChatOpenAI:
    """按 ENV 构造指向多模态端点的 OpenAI 兼容 chat model。

    绘图场景要求输出稳定可解析的 Mermaid 代码块，temperature 默认取低值；
    超时/重试沿用 chat 模型的全局配置（缺省 60s / 2 次）。
    """
    return ChatOpenAI(
        model=ENV.visual_model_name,
        base_url=ENV.visual_api_url,
        api_key=ENV.visual_api_key,
        temperature=temperature,
        timeout=ENV.chat_timeout,
        max_retries=ENV.chat_max_retries,
    )
