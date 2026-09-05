"""
Image 图像生成模型 client 工厂。

统一封装指向 OpenAI 兼容图像生成端点（images/generations）的 client 构造逻辑，
业务代码通过 build_image_client() 获取模型实例、generate_image() 直接生成；
模型名与端点由配置快照 CFG.image 决定（来源 sys_model_config 的 image 角色行，
写时刷新），与 chat/visual/rerank 模型各司其职（对齐 model/visual/factory.py
的工厂约定）。

生图规格中只有 size/quality 属运行期可调项，存于 image 角色行的 extra（JSONB），经配置
快照透传后在此归一为请求入参——调用方只传 prompt/n 与需要覆盖的规格，缺省一律取
extra，前端「模型管理」改后免重启生效。取值域对齐 OpenAI 兼容 images/generations
（参考 gettoken.dev 稳定生图 API）：size 支持 auto 与 1024x1024/1536x1024/
1024x1536/2048x2048/4096x4096 等 "<宽>x<高>" 字面量（按最长边分档计费），
quality 取 auto/low/medium/high。
输出侧参数写死、不做配置项：output_format 固定 webp（同质量下体积小于 png/jpeg），
output_compression 固定 80（上游默认通常为 100 即几乎不压缩；story 场景要落盘大量
关键帧与角色立绘，体积敏感，80 在肉眼几乎无损的前提下明显省体积）。
"""

from functools import cache

from openai import OpenAI

from core.config_snapshot import CFG

# 生图规格缺省值（extra 未配置或键缺失时回落，与前端字典 is_default 项一致）
DEFAULT_SIZE = "1024x1024"
DEFAULT_QUALITY = "auto"
# 输出侧参数写死：不入 extra、不做配置项，要调整直接改这两个常量。
# webp 同质量下体积小于 png/jpeg 且恒支持压缩率；80 对比上游默认（通常 100，
# 几乎不压缩）明显省体积且肉眼几乎无损。
OUTPUT_FORMAT = "webp"
OUTPUT_COMPRESSION = 80


@cache
def _build_image_client(
    api_url: str, api_key: str, timeout: int | None, max_retries: int | None
) -> OpenAI:
    """按配置指纹构造 OpenAI client 单例（指纹相同即复用，跨请求 keep-alive）。"""
    return OpenAI(
        base_url=api_url,
        api_key=api_key,
        timeout=timeout,
        max_retries=max_retries,
    )


def build_image_client() -> OpenAI:
    """按配置快照构造指向图像生成端点的 OpenAI client。

    端点/凭证由 image 角色自身配置；timeout 为 NULL 时透传 None（回落 SDK
    默认 600s）——图像生成耗时普遍长于对话，不套用 chat 的 60s 缺省。
    """
    return _build_image_client(
        api_url=CFG.image.api_url,
        api_key=CFG.image.api_key,
        timeout=CFG.image.timeout,
        max_retries=CFG.image.max_retries,
    )


def _spec(extra: dict, key: str, override: str | None, default: str) -> str:
    """解析字符串型规格参数：调用方覆盖 > extra 配置 > 代码缺省。

    extra 中的非字符串/空白值视为未配置（回落缺省），避免脏配置直传上游报错。
    """
    for candidate in (override, extra.get(key), default):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return default


def generate_image(
    prompt: str,
    size: str | None = None,
    n: int = 1,
    quality: str | None = None,
) -> list[str]:
    """调用 images/generations 生成图像，返回图片内容列表（base64 或 URL）。

    model 取配置快照 CFG.image.model_name，output_format/output_compression 为写死
    常量（三者调用方均不传）；size/quality 为 None 时取 CFG.image.extra 的配置值，
    extra 亦缺失则回落本模块缺省（1024x1024 / auto）——调用方仅在需要偏离全局
    配置时显式传参（如关键帧按分镜比例出横版图）。
    调用方自行决定图片内容的落盘/透传方式（b64_json 解码或 url 直链）。
    """
    extra = CFG.image.extra or {}
    resp = build_image_client().images.generate(
        model=CFG.image.model_name,
        prompt=prompt,
        n=n,
        size=_spec(extra, "size", size, DEFAULT_SIZE),
        quality=_spec(extra, "quality", quality, DEFAULT_QUALITY),
        output_format=OUTPUT_FORMAT,
        output_compression=OUTPUT_COMPRESSION,
    )
    return [item.b64_json or item.url or "" for item in resp.data]
