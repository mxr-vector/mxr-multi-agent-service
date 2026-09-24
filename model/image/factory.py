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

import base64
from functools import cache
import time

import httpx
from openai import OpenAI

from core.config_snapshot import CFG
from utils.logger import logger

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


def _load_image_file_tuple(img_ref: str | bytes) -> tuple[str, bytes, str]:
    """把参考图（相对路径/URL/base64/bytes）转为 (文件名, 二进制, mime)。"""
    if isinstance(img_ref, bytes):
        return ("reference.png", img_ref, "image/png")
    text = str(img_ref).strip()
    if text.startswith("data:image/"):
        header, b64_data = text.split(",", 1)
        mime = header.split(";")[0].replace("data:", "").strip()
        ext = mime.split("/")[-1] if "/" in mime else "png"
        return (f"reference.{ext}", base64.b64decode(b64_data), mime)
    if text.startswith(("http://", "https://")):
        resp = httpx.get(text, timeout=60.0, follow_redirects=True)
        resp.raise_for_status()
        ext = text.split("?")[0].rsplit(".", 1)[-1].lower()
        mime = f"image/{ext}" if ext in ("png", "jpg", "jpeg", "webp") else "image/png"
        return (f"reference.{ext}", resp.content, mime)
    from service.story.storage import resolve_upload_path

    path = resolve_upload_path(text)
    ext = path.suffix.lstrip(".").lower()
    mime = f"image/{ext}" if ext in ("png", "jpg", "jpeg", "webp") else "image/png"
    return (path.name, path.read_bytes(), mime)


def generate_image(
    prompt: str,
    size: str | None = None,
    n: int = 1,
    quality: str | None = None,
    reference_images: list[str | bytes] | None = None,
) -> list[str]:
    """调用 OpenAI 兼容图像生成端点，返回图片内容列表（base64 或 URL）。

    - 未传参考图：调用 images.generate 标准端点出图；
    - 传入参考图：优先基于 OpenAI images.edit 端点进行参考图生图，上游未实现时
      自动降级使用 images.generate 携带 extra_body 兼容字段。
    """
    extra = CFG.image.extra or {}
    client = build_image_client()
    target_size = _spec(extra, "size", size, DEFAULT_SIZE)
    target_quality = _spec(extra, "quality", quality, DEFAULT_QUALITY)

    t0 = time.monotonic()
    ref_count = len(reference_images) if reference_images else 0
    logger.info(
        f"[IMAGE] 发起生图请求: model={CFG.image.model_name}, size={target_size}, quality={target_quality}, ref_count={ref_count}"
    )

    if reference_images:
        loaded_files = []
        for ref in reference_images:
            if not ref:
                continue
            try:
                loaded_files.append(_load_image_file_tuple(ref))
            except Exception as exc:
                logger.warning(f"[IMAGE] 参考图加载失败，已跳过 ({ref}): {exc}")
        if loaded_files:
            b64_list = [
                f"data:{f[2]};base64,{base64.b64encode(f[1]).decode()}"
                for f in loaded_files
            ]
            primary_file = (loaded_files[0][0], loaded_files[0][1], loaded_files[0][2])

            enhanced_prompt = prompt
            if "参考图" not in prompt and "reference" not in prompt.lower():
                if len(loaded_files) > 1:
                    enhanced_prompt = (
                        f"根据提供的多个出场角色参考图生成画面，严格保持参考图中对应人物的外貌特征、五官发型与服饰设定。{prompt}"
                    )
                else:
                    enhanced_prompt = (
                        f"根据参考图生成形象，严格保持参考图中的人物特征、五官发型与造型设计。{prompt}"
                    )

            extra_body_multi = {
                "images": b64_list,
                "image": b64_list[0],
                "reference_images": b64_list,
            }

            # 多参考图场景（如关键帧多出场角色同框）：
            # OpenAI 标准 images.edit 端点仅接受单张 image 文件入参，会造成多图截断；
            # 优先采用 images.generate 并通过 extra_body 携带完整多图列表（兼容 images/reference_images）
            if len(loaded_files) > 1:
                try:
                    resp = client.images.generate(
                        model=CFG.image.model_name,
                        prompt=enhanced_prompt,
                        n=n,
                        size=target_size,
                        quality=target_quality,
                        output_format=OUTPUT_FORMAT,
                        output_compression=OUTPUT_COMPRESSION,
                        extra_body=extra_body_multi,
                    )
                    cost = time.monotonic() - t0
                    logger.info(f"[IMAGE] 多参考图 images.generate 成功耗时={cost:.2f}s")
                    return [item.b64_json or item.url or "" for item in resp.data]
                except Exception as exc:
                    logger.warning(
                        f"[IMAGE] 多参考图 images.generate + extra_body 失败 ({exc})，回退尝试 images.edit (主参考图)"
                    )
                    try:
                        resp = client.images.edit(
                            model=CFG.image.model_name,
                            image=primary_file,
                            prompt=enhanced_prompt,
                            n=n,
                            size=target_size,
                            quality=target_quality,
                            output_format=OUTPUT_FORMAT,
                            output_compression=OUTPUT_COMPRESSION,
                        )
                        cost = time.monotonic() - t0
                        logger.info(f"[IMAGE] images.edit 降级成功耗时={cost:.2f}s")
                        return [item.b64_json or item.url or "" for item in resp.data]
                    except Exception as edit_exc:
                        logger.error(f"[IMAGE] images.edit 降级亦失败: {edit_exc}")
                        raise edit_exc from exc

            # 单参考图场景：优先尝试标准 images.edit 端点（仅传文件与提示词，避免 extra_body 重复发送巨量 base64），
            # 失败后降级 images.generate + extra_body
            try:
                resp = client.images.edit(
                    model=CFG.image.model_name,
                    image=primary_file,
                    prompt=enhanced_prompt,
                    n=n,
                    size=target_size,
                    quality=target_quality,
                    output_format=OUTPUT_FORMAT,
                    output_compression=OUTPUT_COMPRESSION,
                )
                cost = time.monotonic() - t0
                logger.info(f"[IMAGE] 单参考图 images.edit 成功耗时={cost:.2f}s")
                return [item.b64_json or item.url or "" for item in resp.data]
            except Exception as exc:
                logger.warning(
                    f"[IMAGE] images.edit 调用失败 ({exc})，尝试兼容模式 images.generate + extra_body"
                )
                resp = client.images.generate(
                    model=CFG.image.model_name,
                    prompt=enhanced_prompt,
                    n=n,
                    size=target_size,
                    quality=target_quality,
                    output_format=OUTPUT_FORMAT,
                    output_compression=OUTPUT_COMPRESSION,
                    extra_body=extra_body_multi,
                )
                cost = time.monotonic() - t0
                logger.info(f"[IMAGE] 兼容模式 images.generate 成功耗时={cost:.2f}s")
                return [item.b64_json or item.url or "" for item in resp.data]

    resp = client.images.generate(
        model=CFG.image.model_name,
        prompt=prompt,
        n=n,
        size=target_size,
        quality=target_quality,
        output_format=OUTPUT_FORMAT,
        output_compression=OUTPUT_COMPRESSION,
    )
    cost = time.monotonic() - t0
    logger.info(f"[IMAGE] 无参考图 images.generate 成功耗时={cost:.2f}s")
    return [item.b64_json or item.url or "" for item in resp.data]
