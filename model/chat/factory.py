"""
Chat 模型 client 工厂。

统一封装指向 vLLM（OpenAI 兼容接口）的 chat model 构造逻辑，业务代码通过
build_chat_model() 获取模型实例，无需关心 provider / 模型名 / 认证参数等细节。
provider 与模型名由 ENV 决定（CHAT_MODEL_NAME / CHAT_API_URL / CHAT_API_KEY）。
"""

from langchain_openai import ChatOpenAI

from utils.env import ENV

# reasoning_effort 关闭档：该值（或 None）表示关闭思考，不下发 reasoning_effort
REASONING_EFFORT_OFF = "off"


def build_chat_model(
    temperature: float = 2, reasoning_effort: str | None = None
) -> ChatOpenAI:
    """按 ENV 构造指向 vLLM 的 OpenAI 兼容 chat model；reasoning_effort 控制思考强度。

    reasoning_effort 为 None 或 'off' 时重置为 None（不下发该参数）关闭思考；
    其余取值（low/medium/high 等）透传给模型开启对应思考强度。
    思考模式与否均支持工具调用（tool_choice / function_calling）。
    """
    effort = (
        None
        if not reasoning_effort or reasoning_effort.lower() == REASONING_EFFORT_OFF
        else reasoning_effort
    )
    return ChatOpenAI(
        model=ENV.chat_model_name,
        base_url=ENV.chat_api_url,
        api_key=ENV.chat_api_key,
        temperature=temperature,
        reasoning_effort=effort,
    )
