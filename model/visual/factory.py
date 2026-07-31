"""
Visual 多模态模型 client 工厂。

统一封装指向 OpenAI 兼容接口（需支持 vision）的多模态 chat model 构造逻辑，
绘图模块通过 build_visual_model() 获取模型实例；模型名与端点由配置快照 CFG.visual
决定（来源 sys_model_config 的 visual 角色行），与 chat/rewrite 模型各司其职
（对齐 model/chat/factory.py 的工厂约定）。
"""

from langchain_openai import ChatOpenAI

from core.config_snapshot import CFG


def build_visual_model(temperature: float = 0.2) -> ChatOpenAI:
    """按配置快照构造指向多模态端点的 OpenAI 兼容 chat model。

    绘图场景要求输出稳定可解析的 Mermaid 代码块，temperature 默认取低值；
    超时/重试由 visual 角色自身配置（缺省 60s / 2 次）。
    """
    return ChatOpenAI(
        model=CFG.visual.model_name,
        base_url=CFG.visual.api_url,
        api_key=CFG.visual.api_key,
        temperature=temperature,
        timeout=CFG.visual.timeout,
        max_retries=CFG.visual.max_retries,
    )
