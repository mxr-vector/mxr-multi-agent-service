"""
Video 视频生成模型 client 工厂（DashScope 视频合成）。

封装 DashScope VideoSynthesis 的异步任务生命周期：提交任务 → 轮询任务 →
取回视频地址。业务代码通过 submit_video() / get_video_task() /
wait_video_task() / generate_video() 使用，无需关心 SDK 协议与端点拼接。

模型名、端点与凭证由配置快照 CFG.video 决定（来源 sys_model_config 的
video 角色行，写时刷新）。可调规格（resolution/ratio/duration）存于 video
角色行的 extra（JSONB）：调用方覆盖 > extra 配置 > 代码缺省，前端「模型
管理」改后免重启生效。

端点拼接：SDK 以 base_address 为前缀拼出
`{base_address}/services/aigc/video-generation/video-synthesis`，因此配置的
接口地址既可以是完整合成地址（如 curl 里的 URL，自动截断到 /services 之前），
也可以是 `https://dashscope.aliyuncs.com/api/v1` 这类基地址；只填域名时补
`/api/v1`（对齐 SDK 默认）。

SDK 基于 requests，整套流程为同步阻塞；异步调用方请用 asyncio.to_thread
包裹（与仓库内其他同步 IO 的约定一致）。
"""

import time
from http import HTTPStatus
from urllib.parse import urlparse

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


def _normalize_base_address(api_url: str) -> str:
    """把配置的接口地址归一为 SDK 的 base_address。

    支持三种写法：完整合成地址（截断 /services 及之后）、`.../api/v1`
    基地址（原样使用）、纯域名（补 `/api/v1`）。
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
    if not parsed.path.strip("/"):
        url = f"{url}/api/v1"
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


def submit_video(
    prompt: str,
    resolution: str | None = None,
    ratio: str | None = None,
    duration: int | None = None,
) -> str:
    """提交视频合成任务，返回 DashScope task_id（不等待完成）。"""
    if not prompt or not prompt.strip():
        raise ValueError("视频生成提示词不能为空")
    extra = CFG.video.extra or {}
    payload = {
        "resolution": _spec(extra, "resolution", resolution, DEFAULT_RESOLUTION),
        "ratio": _spec(extra, "ratio", ratio, DEFAULT_RATIO),
        "duration": _int_spec(extra, "duration", duration, DEFAULT_DURATION),
    }
    logger.info(
        f"[VIDEO] 提交视频生成任务: model={CFG.video.model_name}, "
        f"resolution={payload['resolution']}, ratio={payload['ratio']}, "
        f"duration={payload['duration']}"
    )
    resp = VideoSynthesis.async_call(
        model=CFG.video.model_name,
        prompt=prompt.strip(),
        **_request_kwargs(),
        **payload,
    )
    if resp.status_code != HTTPStatus.OK:
        raise RuntimeError(
            f"视频生成任务提交失败: HTTP {resp.status_code} "
            f"{resp.code} {resp.message}"
        )
    task_id = (resp.output or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"视频生成任务提交成功但未返回 task_id: {resp.output}")
    return task_id


def _extract_video_url(output: dict) -> str:
    """从任务输出中提取视频地址，兼容 video_url 与 results[*].url 两种形态。"""
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
    return ""


def get_video_task(task_id: str) -> dict:
    """查询一次任务状态，返回 {task_id, task_status, video_url, code, message, raw}。

    VideoSynthesis.fetch 未透传 base_address（自定义 MaaS 端点必需），
    因此走 BaseAsyncApi.fetch——同一任务查询实现，但接受额外 kwargs。
    """
    resp = BaseAsyncApi.fetch(task_id, **_request_kwargs(include_timeout=False))
    if resp.status_code != HTTPStatus.OK:
        raise RuntimeError(
            f"视频任务查询失败: HTTP {resp.status_code} "
            f"{resp.code} {resp.message}"
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
) -> dict:
    """提交并等待视频生成完成，成功返回任务结构（含 video_url），失败抛 RuntimeError。"""
    task_id = submit_video(
        prompt=prompt,
        resolution=resolution,
        ratio=ratio,
        duration=duration,
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
