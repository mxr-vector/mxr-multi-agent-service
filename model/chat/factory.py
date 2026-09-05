"""
Chat 模型 client 工厂。

统一封装指向 vLLM（OpenAI 兼容接口）的 chat model 构造逻辑，业务代码通过
build_chat_model() 获取模型实例，无需关心 provider / 模型名 / 认证参数等细节。
模型名与端点由配置快照 CFG.chat 决定（来源 sys_model_config 的 chat 角色行，
写时刷新）；实例按配置指纹缓存复用（ChatOpenAI 内部持有 httpx 连接池，复用
可跨请求 keep-alive，省去每请求 TCP/TLS 握手），指纹含全部影响构造的配置项，
配置热更新后指纹变化自然构造新实例，旧实例随缓存淘汰，无需额外失效钩子。
"""

from functools import cache

from langchain_openai import ChatOpenAI

from core.config_snapshot import CFG

# reasoning_effort 关闭档：该值（或 None）表示关闭思考，不下发 reasoning_effort
REASONING_EFFORT_OFF = "off"


@cache
def _build_chat_model(
    model_name: str,
    api_url: str,
    api_key: str,
    temperature: float,
    reasoning_effort: str | None,
    max_tokens: int,
    timeout: int | None,
    max_retries: int | None,
) -> ChatOpenAI:
    """按配置指纹构造 chat model 实例（指纹相同即复用，见模块 docstring）。"""
    return ChatOpenAI(
        model=model_name,
        base_url=api_url,
        api_key=api_key,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        # 输出上限（max_tokens）由配置快照决定（CHAT_MAX_OUTPUT_TOKENS），
        # 以 OpenAI 兼容的 max_tokens 入参下发；context_window 仅作输入预算计算。
        max_tokens=max_tokens,
        # 单请求超时（秒）与失败重试次数，均由配置快照决定（缺省 60s / 2 次）。
        # 外部 chat API 卡死不返回时按超时中断，避免 respond 节点无限等待。
        timeout=timeout,
        max_retries=max_retries,
    )


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
    chat = CFG.chat
    return _build_chat_model(
        model_name=chat.model_name,
        api_url=chat.api_url,
        api_key=chat.api_key,
        temperature=temperature,
        reasoning_effort=effort,
        max_tokens=CFG.chat_max_output_tokens,
        timeout=chat.timeout,
        max_retries=chat.max_retries,
    )
