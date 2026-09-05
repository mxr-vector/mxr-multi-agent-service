"""
Rewrite / Compression 模型 client 工厂。

与 model/chat/factory.py 职责区分：chat 模型负责对话与最终答案生成，
本模块的模型专注于问题改写、上下文压缩等辅助性任务，便于独立配置、各司其职。
模型名 / 认证参数由配置快照 CFG.rewrite 决定（来源 sys_model_config 的 rewrite 角色行）。
"""

from langchain_openai import ChatOpenAI

from core.config_snapshot import CFG


def build_compression_model(temperature: float = 0) -> ChatOpenAI:
    """按配置快照构造指向 vLLM 的 OpenAI 兼容 rewrite/compression model。

    默认低温度以获得更确定、更贴近原意的改写与压缩结果。
    """
    return ChatOpenAI(
        model=CFG.rewrite.model_name,
        base_url=CFG.rewrite.api_url,
        api_key=CFG.rewrite.api_key,
        temperature=temperature,
        # 反思/重写是检索链路内部调用，只取完整结果：显式禁流式，
        # 保证 token 事件永不进入 langgraph messages 通道外泄进答案帧
        # （此前仅靠 ainvoke 默认非流式这一隐式行为，配置漂移即漏）
        disable_streaming=True,
    )
