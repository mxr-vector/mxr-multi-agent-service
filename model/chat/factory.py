"""
Chat 模型 client 工厂。

统一封装指向 vLLM（OpenAI 兼容接口）的 chat model 构造逻辑，业务代码通过
build_chat_model() 获取模型实例，无需关心 provider / 模型名 / 认证参数等细节。
模型名与端点由配置快照 CFG.chat 决定（来源 sys_model_config 的 chat 角色行，
写时刷新）；图节点每次调用时现造，以便热更新自下一请求生效。
"""

from langchain_openai import ChatOpenAI

from core.config_snapshot import CFG

# reasoning_effort 关闭档：该值（或 None）表示关闭思考，不下发 reasoning_effort
REASONING_EFFORT_OFF = "off"


def build_chat_model(
    temperature: float = 0.7, reasoning_effort: str | None = None
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
        model=CFG.chat.model_name,
        base_url=CFG.chat.api_url,
        api_key=CFG.chat.api_key,
        temperature=temperature,
        reasoning_effort=effort,
        # 输出上限（max_tokens）由配置快照决定（CHAT_MAX_OUTPUT_TOKENS），
        # 以 OpenAI 兼容的 max_tokens 入参下发；context_window 仅作输入预算计算。
        max_tokens=CFG.chat_max_output_tokens,
        # 单请求超时（秒）与失败重试次数，均由配置快照决定（缺省 60s / 2 次）。
        # 外部 chat API 卡死不返回时按超时中断，避免 respond 节点无限等待。
        timeout=CFG.chat.timeout,
        max_retries=CFG.chat.max_retries,
    )
