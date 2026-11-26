"""
对话历史压缩总结（问答 / 剧本共用）。

设计：
- 可用输入预算 = 模型 context_window − 最大输出（extra.max_output），见
  core/config_snapshot.py 的 ModelRoleConfig；
- 当前会话内容估算占可用预算超过 80% 时触发压缩：保留最近一段原文，
  较早历史交给 rewrite/compression 角色总结为要点摘要；
- 摘要由调用方注入系统提示（问答持久化在图状态 history_summary，
  剧本每次拼入 history_block）；问答侧被压缩消息经 RemoveMessage 从
  checkpoint 删除，业务表完整历史不受影响；
- 压缩失败向上抛出，由调用方回退到原有的按预算裁剪，不阻断问答。
"""

import asyncio

from agent.prompts.summary import HISTORY_SUMMARY_PROMPT
from core.config_snapshot import ModelRoleConfig
from model.compression.factory import build_compression_model

# 可用输入预算占用率达到该比例即触发压缩总结
COMPRESS_TRIGGER_RATIO = 0.8
# 压缩后保留最近原文占可用预算的比例（其余旧历史浓缩为摘要）
RECENT_KEEP_RATIO = 0.4
# 摘要正文长度上限（字符），兜住模型未遵守长度约束的异常输出
MAX_SUMMARY_CHARS = 4000
# 压缩总结调用超时（秒）：压缩在首帧前执行，模型无响应时必须尽快降级为裁剪
SUMMARY_TIMEOUT_SECONDS = 180


def available_input_tokens(role: ModelRoleConfig) -> int:
    """可用输入预算 = context_window − max_output（模型单次请求的输入空间）。"""
    return max(0, role.context_window - role.max_output_tokens)


def needs_compression(estimated_tokens: int, available: int) -> bool:
    """当前会话内容估算是否达到触发比例（预算 ≤ 0 时不压缩，交由裁剪兜底）。"""
    return available > 0 and estimated_tokens > available * COMPRESS_TRIGGER_RATIO


def recent_budget(available: int) -> int:
    """压缩后保留最近原文的 token 预算。"""
    return int(available * RECENT_KEEP_RATIO)


async def summarize_history(older_lines: list[str], prior_summary: str = "") -> str:
    """把较早历史行（可含已有摘要）压缩为一段摘要；失败向上抛出由调用方降级。"""
    history = "\n".join(line for line in older_lines if line and line.strip())
    prior_summary = (prior_summary or "").strip()
    if not history:
        return prior_summary
    response = await asyncio.wait_for(
        build_compression_model().ainvoke(
            [
                {
                    "role": "user",
                    "content": HISTORY_SUMMARY_PROMPT.format(
                        prior_summary=prior_summary or "（无）",
                        history=history,
                    ),
                }
            ]
        ),
        timeout=SUMMARY_TIMEOUT_SECONDS,
    )
    summary = (response.content or "").strip()
    if not summary:
        # 空摘要视为失败：调用方会回退裁剪，绝不能以空摘要换取删除旧消息（信息丢失）
        raise ValueError("压缩模型返回空摘要")
    return summary[:MAX_SUMMARY_CHARS]