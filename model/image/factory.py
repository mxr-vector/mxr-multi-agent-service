"""
Image 图像生成模型 client 工厂。

统一封装指向 OpenAI 兼容图像生成端点（images/generations）的 client 构造逻辑，
业务代码通过 build_image_client() 获取模型实例、generate_image() 直接生成；
模型名与端点由配置快照 CFG.image 决定（来源 sys_model_config 的 image 角色行，
写时刷新），与 chat/visual/rerank 模型各司其职（对齐 model/visual/factory.py
的工厂约定）。
"""

from openai import OpenAI

from core.config_snapshot import CFG


def build_image_client() -> OpenAI:
    """按配置快照构造指向图像生成端点的 OpenAI client。

    端点/凭证由 image 角色自身配置；timeout 为 NULL 时透传 None（回落 SDK
    默认 600s）——图像生成耗时普遍长于对话，不套用 chat 的 60s 缺省。
    """
    return OpenAI(
        base_url=CFG.image.api_url,
        api_key=CFG.image.api_key,
        timeout=CFG.image.timeout,
        max_retries=CFG.image.max_retries,
    )


def generate_image(prompt: str, size: str = "1024x1024", n: int = 1) -> list[str]:
    """调用 images/generations 生成图像，返回图片内容列表（base64 或 URL）。

    model 固定取配置快照 CFG.image.model_name（调用方不传模型名）；
    调用方自行决定图片内容的落盘/透传方式（b64_json 解码或 url 直链）。
    """
    resp = build_image_client().images.generate(
        model=CFG.image.model_name,
        prompt=prompt,
        size=size,
        n=n,
    )
    return [item.b64_json or item.url or "" for item in resp.data]
