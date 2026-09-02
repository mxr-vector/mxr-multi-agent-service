"""
tiktoken token 估算器（chat 输入预算守卫用）。

职责：
- count_tokens(model_name, text)：按 chat 模型名映射 encoding 估算文本 token；
- count_messages_tokens(model_name, messages)：按消息列表估算总 token
  （文本 content 计 token，多模态 content 列表仅计 text 部分，消息级固定开销计入）；
- Encoding 对象按模型名 lru_cache 缓存，避免重复加载；未知模型名回落
  cl100k_base 保守估算（估算偏差由输入预算的安全边际兜底）。

对齐项目惯例：业务代码统一经本模块估算 token，不直接 import tiktoken。
"""

import functools

import tiktoken
from langchain_core.messages import BaseMessage

# OpenAI 已知模型 → encoding 精确映射（覆盖 langchain-openai 常用 chat 模型）；
# 其余模型（Qwen 等本地部署）回落 _FALLBACK_ENCODING
_ENCODING_BY_MODEL = {
    # o200k_base 系
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4.1": "o200k_base",
    "gpt-4.1-mini": "o200k_base",
    "o1": "o200k_base",
    "o1-mini": "o200k_base",
    "o3": "o200k_base",
    "o3-mini": "o200k_base",
    "o4-mini": "o200k_base",
    "chatgpt-4o-latest": "o200k_base",
    # cl100k_base 系
    "gpt-4": "cl100k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "gpt-35-turbo": "cl100k_base",
}
_FALLBACK_ENCODING = "cl100k_base"

# 每条消息的固定开销（role 标记 + 分隔符等，按 OpenAI chat 消息格式保守取值）
_MESSAGE_FIXED_TOKENS = 4


@functools.lru_cache(maxsize=32)
def _get_encoding(model_name: str) -> tiktoken.Encoding:
    """按模型名解析 encoding；未知模型回落 cl100k_base（保守估算，只多不少）。"""
    enc_name = _ENCODING_BY_MODEL.get((model_name or "").lower(), _FALLBACK_ENCODING)
    try:
        return tiktoken.get_encoding(enc_name)
    except Exception:
        return tiktoken.get_encoding(_FALLBACK_ENCODING)


def count_tokens(model_name: str, text: str | None) -> int:
    """估算单段文本的 token 数；空文本返回 0。"""
    if not text:
        return 0
    return len(_get_encoding(model_name).encode(text))


def _content_tokens(model_name: str, content) -> int:
    """按消息 content 结构估算：str 直接计；多模态列表仅计 text 部分。"""
    if isinstance(content, str):
        return count_tokens(model_name, content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                total += count_tokens(model_name, part["text"])
            elif isinstance(part, str):
                total += count_tokens(model_name, part)
        return total
    return 0


def count_messages_tokens(model_name: str, messages: list[BaseMessage]) -> int:
    """估算消息列表总 token（含每消息固定开销）。"""
    total = 0
    for message in messages:
        total += _MESSAGE_FIXED_TOKENS
        total += _content_tokens(model_name, getattr(message, "content", None))
    return total


if __name__ == "__main__":
    # 手动冒烟：uv run python utils/token_count.py
    from langchain_core.messages import HumanMessage, SystemMessage

    sample = "你好，请介绍一下 Flink CDC 支持哪些数据库。"
    print(f"已知模型 gpt-4o: {count_tokens('gpt-4o', sample)} token")
    print(
        f"未知模型 Qwen3-Chat-30B-AWQ: {count_tokens('Qwen3-Chat-30B-AWQ', sample)} token"
    )
    msgs = [SystemMessage(content="你是一个严谨的助手。"), HumanMessage(content=sample)]
    print(f"消息列表估算: {count_messages_tokens('Qwen3-Chat-30B-AWQ', msgs)} token")
