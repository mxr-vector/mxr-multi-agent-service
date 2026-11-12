"""
Video 视频生成模型 client 工厂。

支持两套上游协议，按配置的接口地址自动判定，可用 video 角色
extra.video_protocol 显式覆盖（"dashscope" | "openai" | "auto"）：

- dashscope：DashScope 原生异步任务协议，SDK 以 base_address 拼出
  `{base_address}/services/aigc/video-generation/video-synthesis`，任务查询走
  `/tasks/{task_id}`。适用于 dashscope.aliyuncs.com 与 MaaS / Token Plan 端点；
  接口地址填 OpenAI 兼容基地址（`.../compatible-mode/v1`）时会自动归一为
  原生接口所在的 `/api/v1`。
- openai：聚合网关（如 tokenrhythm.studio）的 OpenAI 风格视频接口
  `POST {base}/videos/generations`、`GET {base}/videos/{task_id}`，请求体为
  `content` 数组（text / image_url + first_frame|reference_image 角色），
  创建返回 202 + 任务 id，轮询成功后从 video_url / result.url 取成片。
  首帧与参考图可同时携带（章节串行衔接），上游拒绝时由业务层降级。

判定规则：接口地址主机属于阿里云 DashScope / MaaS 时走 dashscope，其余
（第三方聚合网关、自建兼容端点）走 openai；无法从域名判断时在 extra 配
`"video_protocol": "dashscope" | "openai"`。

模型名、端点与凭证由配置快照 CFG.video 决定（来源 sys_model_config 的
video 角色行，写时刷新）。可调规格（resolution/ratio/duration）存于 video
角色行的 extra（JSONB）：调用方覆盖 > extra 配置 > 代码缺省，前端「模型
管理」改后免重启生效。wan3.0 文档未暴露 negative_prompt，默认不透传；
如上游确认支持，可在 extra 配 `"supports_negative_prompt": true`。

业务代码通过 submit_video() / get_video_task() / wait_video_task() /
generate_video() 使用，无需关心协议与端点拼接。同步阻塞，异步调用方请用
asyncio.to_thread 包裹（与仓库内其他同步 IO 的约定一致）。
"""

import time
from http import HTTPStatus
from urllib.parse import urlparse

import httpx
from dashscope.aigc.video_synthesis import VideoSynthesis
from dashscope.client.base_api import BaseAsyncApi

from core.config_snapshot import CFG
from utils.logger import logger

# 可调规格缺省值（extra 未配置或键缺失时回落，与前端字典 is_default 项一致）
DEFAULT_RESOLUTION = "480P"
DEFAULT_RATIO = "adaptive"
DEFAULT_DURATION = 5

# 任务终态：进入其中之一即停止轮询
TERMINAL_STATUSES = frozenset({"SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"})

# 轮询间隔与默认总等待上限（秒）：视频合成通常 1~5 分钟，留 15 分钟余量；
# 调用方可通过 wait_video_task/generate_video 的入参覆盖
DEFAULT_POLL_INTERVAL = 5
DEFAULT_WAIT_TIMEOUT = 900

# SDK 会把 base_address 之后的内容拼成 services/aigc/video-generation/video-synthesis
_SERVICES_MARKER = "/services/"

# 阿里云 MaaS / Token Plan 的 OpenAI 兼容基地址后缀。视频生成只有原生异步接口
# 且位于 /api/v1 下，直接使用该地址会拼出 .../compatible-mode/v1/services/...
# 并报 "url error, please check url"，因此归一为原生接口基地址
_OPENAI_COMPATIBLE_MARKER = "/compatible-mode/v1"
_NATIVE_API_PATH = "/api/v1"

# 协议常量
PROTOCOL_DASHSCOPE = "dashscope"
PROTOCOL_OPENAI = "openai"

# 聚合网关任务状态 → 统一终态/中间态命名（轮询逻辑只认大写统一值）
_OPENAI_STATUS_MAP = {
    "queued": "PENDING",
    "pending": "PENDING",
    "processing": "RUNNING",
    "running": "RUNNING",
    "in_progress": "RUNNING",
    "succeeded": "SUCCEEDED",
    "success": "SUCCEEDED",
    "completed": "SUCCEEDED",
    "failed": "FAILED",
    "error": "FAILED",
    "cancelled": "CANCELED",
    "canceled": "CANCELED",
    "expired": "UNKNOWN",
    "unknown": "UNKNOWN",
}


class VideoApiError(RuntimeError):
    """上游视频接口错误；status_code/code 供业务层判断是否值得回退重试。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _protocol(extra: dict) -> str:
    """解析上游协议：extra 显式配置优先，否则按接口地址主机名自动判定。"""
    mode = str(extra.get("video_protocol") or "auto").strip().lower()
    if mode in (PROTOCOL_DASHSCOPE, PROTOCOL_OPENAI):
        return mode
    host = (urlparse(CFG.video.api_url or "").hostname or "").lower()
    if host == "dashscope.aliyuncs.com" or host.endswith(".maas.aliyuncs.com"):
        return PROTOCOL_DASHSCOPE
    return PROTOCOL_OPENAI


def _normalize_base_address(api_url: str) -> str:
    """把配置的接口地址归一为 DashScope SDK 的 base_address。

    支持四种写法：完整合成地址（截断 /services 及之后）、`.../api/v1`
    基地址（原样使用）、OpenAI 兼容基地址（`.../compatible-mode/v1` 改写为
    `.../api/v1`）、纯域名（补 `/api/v1`）。
    """
    url = (api_url or "").strip().rstrip("/")
    if not url:
        raise ValueError("视频模型接口地址未配置")
    index = url.find(_SERVICES_MARKER)
    if index != -1:
        url = url[:index].rstrip("/")
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise ValueError(f"视频模型接口地址非法: {api_url!r}") from exc
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"视频模型接口地址非法: {api_url!r}")
    path = parsed.path.rstrip("/")
    if path.endswith(_OPENAI_COMPATIBLE_MARKER):
        url = url[: -len(_OPENAI_COMPATIBLE_MARKER)].rstrip("/") + _NATIVE_API_PATH
    elif not path.strip("/"):
        url = f"{url}{_NATIVE_API_PATH}"
    return url


def _openai_base_address(api_url: str) -> str:
    """把配置的接口地址归一为聚合网关基地址（拼接 /videos 系列路径的根）。

    支持 `https://host/v1`、`https://host/v1/videos/generations` 与纯域名
    （补 `/v1`），统一产出 `https://host/v1` 形态。
    """
    url = (api_url or "").strip().rstrip("/")
    if not url:
        raise ValueError("视频模型接口地址未配置")
    for suffix in ("/videos/generations", "/videos"):
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
            break
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise ValueError(f"视频模型接口地址非法: {api_url!r}") from exc
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"视频模型接口地址非法: {api_url!r}")
    if not parsed.path.strip("/"):
        url = f"{url}/v1"
    return url


def _request_kwargs(include_timeout: bool = True) -> dict:
    """SDK 公共入参：凭证与端点。

    api_key 为空时传 None，让 SDK 回落 DASHSCOPE_API_KEY 环境变量。
    timeout 仅用于提交请求（SDK 任务查询在 _get 内固定 300s，传了也不生效，
    因此 include_timeout=False 时不下发）。
    """
    kwargs: dict = {
        "api_key": CFG.video.api_key or None,
        "base_address": _normalize_base_address(CFG.video.api_url),
    }
    if include_timeout and CFG.video.timeout:
        kwargs["request_timeout"] = CFG.video.timeout
    return kwargs


def _spec(extra: dict, key: str, override: str | None, default: str) -> str:
    """解析字符串型规格：调用方覆盖 > extra 配置 > 代码缺省。

    extra 中的非字符串/空白值视为未配置（回落缺省），避免脏配置直传上游报错。
    """
    for candidate in (override, extra.get(key), default):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return default


def _int_spec(extra: dict, key: str, override: int | None, default: int) -> int:
    """解析正整数型规格（duration）：非法或非正数回落后续候选。"""
    for candidate in (override, extra.get(key), default):
        if isinstance(candidate, bool):
            continue
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return default


def _first_frame_mode(extra: dict, override: str | None) -> str:
    """首帧入参形态：media(wan3.0/2.7) 或 img_url(2.1-2.6 及兼容端点)。

    调用方 override > extra.first_frame_mode > 按模型名自动判定。
    MaaS 自定义别名无法从名字判断时，可在 video 角色 extra 显式配置
    `"first_frame_mode": "media" | "img_url"`。
    """
    mode = override or extra.get("first_frame_mode") or "auto"
    mode = str(mode).strip().lower()
    if mode in ("media", "img_url"):
        return mode
    model = (CFG.video.model_name or "").lower()
    return "media" if ("wan3" in model or "2.7" in model) else "img_url"


def _normalize_images(
    first_frame_url: str | None, reference_image_urls: list[str] | None
) -> tuple[str, list[str]]:
    """清洗图片入参：空白剔除、保持参考图顺序（按【图1】【图2】引用）。"""
    images = [
        url.strip()
        for url in (reference_image_urls or [])
        if isinstance(url, str) and url.strip()
    ]
    return (first_frame_url or "").strip(), images


def _submit_openai(
    prompt: str,
    frame_url: str,
    images: list[str],
    *,
    resolution: str,
    ratio: str,
    duration: int,
    negative_prompt: str | None,
    prompt_extend: bool | None,
    seed: int | None,
    extra: dict,
) -> str:
    """按聚合网关协议提交任务（POST {base}/videos/generations）。

    首帧与参考图可同时下发：上一章成片尾帧作 first_frame，本章关键帧作
    reference_image（串行衔接）；上游不支持混合入参时由业务层降级重试。
    """
    content: list[dict] = [{"type": "text", "text": prompt}]
    if frame_url:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": frame_url},
                "role": "first_frame",
            }
        )
    content.extend(
        {
            "type": "image_url",
            "image_url": {"url": url},
            "role": "reference_image",
        }
        for url in images
    )

    payload: dict = {
        "model": CFG.video.model_name,
        "content": content,
        "resolution": resolution,
        "ratio": ratio,
        "duration": duration,
    }
    if prompt_extend is not None:
        payload["prompt_extend"] = prompt_extend
    if seed is not None:
        payload["seed"] = seed
    # 网关文档未暴露 negative_prompt，默认不透传避免 UNKNOWN_FIELD 校验报错
    supports_negative = extra.get("supports_negative_prompt")
    if supports_negative:
        cleaned = (negative_prompt or "").strip()
        if cleaned:
            payload["negative_prompt"] = cleaned

    url = f"{_openai_base_address(CFG.video.api_url)}/videos/generations"
    data = _openai_request("POST", url, json_body=payload)
    task_id = (
        data.get("id")
        or data.get("task_id")
        or (data.get("output") or {}).get("task_id")
    )
    if not task_id:
        raise VideoApiError(f"视频生成任务提交成功但未返回任务 id: {data}")
    return str(task_id)


def _submit_dashscope(
    prompt: str,
    frame_url: str,
    images: list[str],
    *,
    extra: dict,
    resolution: str,
    ratio: str,
    duration: int,
    first_frame_mode: str | None,
    negative_prompt: str | None,
    prompt_extend: bool | None,
    seed: int | None,
) -> str:
    """按 DashScope 原生协议提交任务（SDK VideoSynthesis.async_call）。"""
    optional = {
        "prompt_extend": prompt_extend,
        "seed": seed,
    }
    # wan3.0 文档未暴露 negative_prompt，未显式声明支持时不透传，避免严格校验报错
    supports_negative = extra.get("supports_negative_prompt")
    if supports_negative is None:
        supports_negative = "wan3" not in (CFG.video.model_name or "").lower()
    if supports_negative:
        optional["negative_prompt"] = (negative_prompt or "").strip() or None

    if images or frame_url:
        if _first_frame_mode(extra, first_frame_mode) == "media":
            media: list[dict] = []
            if frame_url:
                media.append({"type": "first_frame", "url": frame_url})
            media.extend({"type": "reference_image", "url": url} for url in images)
            optional["media"] = media
        else:
            if frame_url:
                optional["img_url"] = frame_url
            if images:
                optional["reference_urls"] = images
    payload = {
        "resolution": resolution,
        "ratio": ratio,
        "duration": duration,
        **{key: value for key, value in optional.items() if value is not None},
    }
    resp = VideoSynthesis.async_call(
        model=CFG.video.model_name,
        prompt=prompt,
        **_request_kwargs(),
        **payload,
    )
    if resp.status_code != HTTPStatus.OK:
        raise VideoApiError(
            f"视频生成任务提交失败: HTTP {resp.status_code} {resp.code} {resp.message}",
            status_code=resp.status_code,
            code=resp.code,
        )
    task_id = (resp.output or {}).get("task_id")
    if not task_id:
        raise VideoApiError(f"视频生成任务提交成功但未返回 task_id: {resp.output}")
    return task_id


def submit_video(
    prompt: str,
    resolution: str | None = None,
    ratio: str | None = None,
    duration: int | None = None,
    *,
    first_frame_url: str | None = None,
    reference_image_urls: list[str] | None = None,
    first_frame_mode: str | None = None,
    negative_prompt: str | None = None,
    prompt_extend: bool | None = None,
    seed: int | None = None,
) -> str:
    """提交视频合成任务，返回上游 task id（不等待完成）。

    参考图：单图可作首帧；多图（章节级一次生成）作为 reference_image 序列
    传入，由提示词按【图1】【图2】顺序引用。first_frame_url 与
    reference_image_urls 可同时传入（上一章尾帧 + 本章关键帧的串行衔接），
    协议按 CFG.video.api_url 自动判定，见模块 docstring。
    """
    if not prompt or not prompt.strip():
        raise ValueError("视频生成提示词不能为空")
    extra = CFG.video.extra or {}
    protocol = _protocol(extra)
    frame_url, images = _normalize_images(first_frame_url, reference_image_urls)
    resolution_value = _spec(extra, "resolution", resolution, DEFAULT_RESOLUTION)
    ratio_value = _spec(extra, "ratio", ratio, DEFAULT_RATIO)
    duration_value = _int_spec(extra, "duration", duration, DEFAULT_DURATION)
    logger.info(
        f"[VIDEO] 提交视频生成任务: model={CFG.video.model_name}, protocol={protocol}, "
        f"resolution={resolution_value}, ratio={ratio_value}, "
        f"duration={duration_value}, first_frame={bool(frame_url)}, "
        f"references={len(images)}"
    )
    if protocol == PROTOCOL_OPENAI:
        return _submit_openai(
            prompt.strip(),
            frame_url,
            images,
            resolution=resolution_value,
            ratio=ratio_value,
            duration=duration_value,
            negative_prompt=negative_prompt,
            prompt_extend=prompt_extend,
            seed=seed,
            extra=extra,
        )
    return _submit_dashscope(
        prompt.strip(),
        frame_url,
        images,
        extra=extra,
        resolution=resolution_value,
        ratio=ratio_value,
        duration=duration_value,
        first_frame_mode=first_frame_mode,
        negative_prompt=negative_prompt,
        prompt_extend=prompt_extend,
        seed=seed,
    )


def _extract_video_url(output: dict) -> str:
    """从 DashScope 任务输出中提取视频地址，兼容 video_url 与 results[*].url。"""
    url = output.get("video_url")
    if isinstance(url, str) and url:
        return url
    results = output.get("results")
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            candidate = item.get("video_url") or item.get("url")
            if isinstance(candidate, str) and candidate:
                return candidate
            if isinstance(candidate, dict) and isinstance(candidate.get("url"), str):
                return candidate["url"]
    return ""


def _extract_gateway_video_url(data: dict) -> str:
    """从聚合网关任务响应中提取成片地址。

    覆盖文档中的 `content.video_url`、顶层 `video_url`，以及 `result.url`
    等常见形态；未完成时返回空串。
    """
    content = data.get("content")
    if isinstance(content, dict):
        url = content.get("video_url") or content.get("url")
        if isinstance(url, str) and url:
            return url
    for key in ("video_url", "output"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            url = _extract_video_url(value)
            if url:
                return url
    result = data.get("result")
    if isinstance(result, dict):
        url = result.get("url") or result.get("video_url")
        if isinstance(url, str) and url:
            return url
    return ""


def _map_gateway_status(raw: str) -> str:
    return _OPENAI_STATUS_MAP.get(
        (raw or "").strip().lower(), (raw or "").upper() or "UNKNOWN"
    )


def _openai_request(
    method: str,
    url: str,
    *,
    json_body: dict | None = None,
) -> dict:
    """调用聚合网关并解析 JSON；非 2xx 抛带状态码的 VideoApiError。

    错误体统一为 `{code, message, traceId}`，traceId 一并带入异常便于排障。
    """
    api_key = (CFG.video.api_key or "").strip()
    if not api_key:
        raise ValueError("视频模型 API Key 未配置")
    timeout_total = float(CFG.video.timeout or 600)
    timeout = httpx.Timeout(timeout_total, connect=min(30.0, timeout_total))
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = httpx.request(
            method, url, headers=headers, json=json_body, timeout=timeout
        )
    except httpx.HTTPError as exc:
        raise VideoApiError(f"视频接口请求失败: {url}: {exc}") from exc
    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if resp.status_code >= 400:
        code = data.get("code") or data.get("error_code")
        message = data.get("message") or data.get("error_message") or resp.text[:300]
        trace = data.get("traceId") or data.get("trace_id")
        suffix = f", traceId={trace}" if trace else ""
        raise VideoApiError(
            f"视频接口请求失败: HTTP {resp.status_code} {code or ''} {message}{suffix}".strip(),
            status_code=resp.status_code,
            code=str(code) if code else None,
        )
    return data


def _get_openai_task(task_id: str) -> dict:
    """查询聚合网关任务：GET {base}/videos/{task_id}。"""
    url = f"{_openai_base_address(CFG.video.api_url)}/videos/{task_id}"
    data = _openai_request("GET", url)
    error = data.get("error") if isinstance(data.get("error"), dict) else {}
    return {
        "task_id": str(data.get("id") or data.get("task_id") or task_id),
        "task_status": _map_gateway_status(
            str(data.get("status") or data.get("task_status") or "")
        ),
        "video_url": _extract_gateway_video_url(data),
        "code": data.get("code") or error.get("code"),
        "message": data.get("message") or error.get("message"),
        "raw": data,
    }


def get_video_task(task_id: str) -> dict:
    """查询一次任务状态，返回 {task_id, task_status, video_url, code, message, raw}。

    DashScope 协议下 VideoSynthesis.fetch 未透传 base_address（自定义 MaaS
    端点必需），因此走 BaseAsyncApi.fetch——同一任务查询实现，但接受额外 kwargs。
    """
    if _protocol(CFG.video.extra or {}) == PROTOCOL_OPENAI:
        return _get_openai_task(task_id)
    resp = BaseAsyncApi.fetch(task_id, **_request_kwargs(include_timeout=False))
    if resp.status_code != HTTPStatus.OK:
        raise VideoApiError(
            f"视频任务查询失败: HTTP {resp.status_code} {resp.code} {resp.message}",
            status_code=resp.status_code,
            code=resp.code,
        )
    output = resp.output or {}
    return {
        "task_id": output.get("task_id") or task_id,
        "task_status": str(output.get("task_status") or ""),
        "video_url": _extract_video_url(output),
        "code": output.get("code"),
        "message": output.get("message"),
        "raw": output,
    }


def cancel_remote_video(task_id: str) -> bool:
    """尽力取消上游未完成任务（停止生成时避免继续计费），失败仅告警。"""
    if not task_id:
        return False
    try:
        if _protocol(CFG.video.extra or {}) == PROTOCOL_OPENAI:
            url = f"{_openai_base_address(CFG.video.api_url)}/videos/{task_id}"
            _openai_request("DELETE", url)
            logger.info(f"[VIDEO] 上游任务已取消: task_id={task_id}")
            return True
        resp = BaseAsyncApi.cancel(task_id, **_request_kwargs(include_timeout=False))
        if resp.status_code != HTTPStatus.OK:
            logger.warning(
                f"[VIDEO] 上游任务取消失败: task_id={task_id}, "
                f"HTTP {resp.status_code} {resp.code} {resp.message}"
            )
            return False
        logger.info(f"[VIDEO] 上游任务已取消: task_id={task_id}")
        return True
    except Exception as exc:  # 已结束/不支持取消：不影响本地停止
        logger.warning(f"[VIDEO] 上游任务取消异常 task_id={task_id}: {exc}")
        return False


def wait_video_task(
    task_id: str,
    wait_timeout: float = DEFAULT_WAIT_TIMEOUT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> dict:
    """轮询任务直到终态或超时，返回 get_video_task 的结构；超时抛 TimeoutError。"""
    deadline = time.monotonic() + wait_timeout
    while True:
        task = get_video_task(task_id)
        status = task["task_status"]
        if status in TERMINAL_STATUSES:
            logger.info(f"[VIDEO] 任务结束: task_id={task_id}, status={status}")
            return task
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"视频生成任务超时（{wait_timeout}s, task_id={task_id}, status={status}）"
            )
        time.sleep(poll_interval)


def generate_video(
    prompt: str,
    resolution: str | None = None,
    ratio: str | None = None,
    duration: int | None = None,
    wait_timeout: float = DEFAULT_WAIT_TIMEOUT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    *,
    first_frame_url: str | None = None,
    reference_image_urls: list[str] | None = None,
    first_frame_mode: str | None = None,
    negative_prompt: str | None = None,
    prompt_extend: bool | None = None,
    seed: int | None = None,
) -> dict:
    """提交并等待视频生成完成，成功返回任务结构（含 video_url），失败抛 RuntimeError。"""
    task_id = submit_video(
        prompt=prompt,
        resolution=resolution,
        ratio=ratio,
        duration=duration,
        first_frame_url=first_frame_url,
        reference_image_urls=reference_image_urls,
        first_frame_mode=first_frame_mode,
        negative_prompt=negative_prompt,
        prompt_extend=prompt_extend,
        seed=seed,
    )
    task = wait_video_task(
        task_id,
        wait_timeout=wait_timeout,
        poll_interval=poll_interval,
    )
    if task["task_status"] != "SUCCEEDED":
        raise RuntimeError(
            f"视频生成失败: status={task['task_status']}, "
            f"code={task['code']}, message={task['message']}"
        )
    return task
