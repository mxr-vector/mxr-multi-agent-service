"""
Chat 模型 client 工厂。

统一封装指向 vLLM（OpenAI 兼容接口）的 chat model 构造逻辑，业务代码通过
build_chat_model() 获取模型实例，无需关心 provider / 模型名 / 认证参数等细节。
provider 与模型名由 ENV 决定（CHAT_MODEL_NAME / CHAT_API_URL / CHAT_API_KEY）。
"""

from langchain_openai import ChatOpenAI

from utils.env import ENV


def build_chat_model(
    temperature: float = 2, reasoning_effort: str = "medium"
) -> ChatOpenAI:
    """按 ENV 构造指向 vLLM 的 OpenAI 兼容 chat model；reasoning_effort 控制思考强度。"""
    return ChatOpenAI(
        model=ENV.chat_model_name,
        base_url=ENV.chat_api_url,
        api_key=ENV.chat_api_key,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
    )
