"""
剧本模块视频片段生成业务层：章节片段并发生成与集间衔接片段。

- 章节生成：一次提交该章全部关键帧参考图，产出一个片段；各章相互独立、
  按项目并发上限并行排队，不做上下集串行依赖。
- 集间衔接：对相邻两集已完成片段，抽取上一集成片尾帧与下一集成片首帧，
  以 first_frame + last_frame 生成一段过渡片段（kind=transition），供外部
  剪辑插入两集之间，解决跨集画面跳变。
- 关键帧本地图片压缩后转 base64 data URI 作为参考图/首帧（DashScope 原生
  协议 wan3.0 走 media、旧模型走 img_url；聚合网关协议走 content 数组的
  first_frame / reference_image 角色）。DashScope 原生接口不允许参考图与
  首尾帧并存：章节生成优先参考图，衔接片段只带首尾帧；提交被拒（400/413/
  422）或任务因入参不兼容失败（InvalidParameter）时按图片形态逐级降级，
  不再静默回退纯文生，避免成片与关键帧人物完全不一致。
- 任务生命周期：queued → generating → done / failed / cancelled。后台协程
  异步轮询上游任务（等待期间可取消），完成后立即下载落盘，章节片段封面
  优先复用本章首关键帧，失败再抽视频首帧。
- 项目级并发上限 MAX_CONCURRENT_VIDEO_TASKS；不同章节并行生成，互不阻塞。
- 只产出可下载的单片段，整片由用户自行下载后外部组装。
"""

import asyncio
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select, update
from uuid_utils.compat import uuid7

from agent.constants.enums.story import StoryKeyframeStatus, StoryTaskType
from core.config_snapshot import CFG
from database.postgre_client import get_session
from database.story.project import KeyframeRepository, ProjectRepository
from database.story.session import GenerationTaskRepository
from database.story.video import RUNNING_STATUSES, VideoRepository
from entity.story.session import StoryGenerationTask
from entity.story.video import StoryVideo
from exception.bad_except import bad_except
from model.video.factory import (
    DEFAULT_DURATION,
    DEFAULT_RATIO,
    DEFAULT_RESOLUTION,
    TERMINAL_STATUSES,
    cancel_remote_video,
    get_video_task,
    submit_video,
    supports_last_frame,
    supports_mixed_media,
)
from service.story.project import ProjectService
from service.story.storage import (
    image_to_reference_data_uri,
    resolve_upload_path,
    unlink_quietly,
)
from service.story.video import (
    COVER_SUBDIR,
    LINK_FRAME_SUBDIR,
    LINK_KIND,
    VIDEO_EXTENSIONS,
    VIDEO_SUBDIR,
    extract_first_frame,
    extract_last_frame,
    probe_video_meta,
    video_local_files,
)
from utils.env import ENV
from utils.logger import logger

# 项目级视频生成并发上限：视频合成单次成本高、耗时长，保持 queued 排队更稳
MAX_CONCURRENT_VIDEO_TASKS = 3

# 上游任务轮询间隔与总等待上限（秒）：视频通常 1~5 分钟，留 30 分钟余量
VIDEO_POLL_INTERVAL = 5.0
VIDEO_WAIT_TIMEOUT = 1800.0

# 生成结果下载上限（MB）：防止异常大文件占满磁盘
GENERATED_VIDEO_MAX_MB = 2048

# 用户编辑后的整章提示词/章节内容上限（章节 Prompt 含全部参考图说明）
VIDEO_PROMPT_MAX_CHARS = 4000
CHAPTER_CONTENT_MAX = 3000

# 上游取消失败/超时不影响本地停止流程
REMOTE_CANCEL_TIMEOUT = 5.0

# 集间衔接片段默认提示词（帧文件目录与 kind 标记见 service/story/video.py）
LINK_PROMPT_DEFAULT = (
    "集间过渡片段：从上一集的结尾画面开始，自然过渡到下一集的开始画面，"
    "保持人物、服装、场景、光线与镜头方向一致，画面连贯，避免跳切。"
)

# 运行期任务注册表：video_id_hex -> asyncio.Task；项目信号量按需创建
_video_tasks: dict[str, asyncio.Task] = {}
_project_semaphores: dict[str, asyncio.Semaphore] = {}
# 建行互斥锁：串行化"校验 + 建行"窗口，避免批量并发提交时重复落库
_project_task_locks: dict[str, asyncio.Lock] = {}


@dataclass
class _ChapterInputs:
    """单章提交前解析出的图片入参。"""

    reference_images: list[str]
    first_frame_file: str | None
    cover_image_file: str | None


def _project_semaphore(project_hex: str) -> asyncio.Semaphore:
    """获取项目级视频生成信号量（懒创建，同一事件循环内复用）。"""
    semaphore = _project_semaphores.get(project_hex)
    if semaphore is None:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_VIDEO_TASKS)
        _project_semaphores[project_hex] = semaphore
    return semaphore


def _project_task_lock(project_hex: str) -> asyncio.Lock:
    """获取项目级建行锁（懒创建），串行化批量并发提交的建行窗口。"""
    lock = _project_task_locks.get(project_hex)
    if lock is None:
        lock = asyncio.Lock()
        _project_task_locks[project_hex] = lock
    return lock


def cancel_video_task(video_id: uuid.UUID) -> bool:
    """取消内存中的在途生成任务（删除登记前调用，避免继续消耗上游额度）。"""
    task = _video_tasks.get(video_id.hex)
    if task is None or task.done():
        return False
    task.cancel()
    return True


async def _cancel_remote_task(task_id: str | None) -> None:
    """尽力取消上游任务并限时等待；超时/异常不阻断本地停止。"""
    if not task_id:
        return
    try:
        await asyncio.wait_for(
            asyncio.to_thread(cancel_remote_video, task_id),
            timeout=REMOTE_CANCEL_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning(
            f"[STORY] 上游任务取消超时（{REMOTE_CANCEL_TIMEOUT}s）: {task_id}"
        )
    except Exception as exc:
        logger.warning(f"[STORY] 上游任务取消失败 task_id={task_id}: {exc}")


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _keyframe_label(keyframe) -> str:
    """关键帧展示名：优先名称，其次场景-镜头编号，最后 id。"""
    if keyframe.name and keyframe.name.strip():
        return keyframe.name.strip()
    if keyframe.scene_no is not None and keyframe.shot_no is not None:
        return f"场景{keyframe.scene_no}-镜头{keyframe.shot_no}"
    return keyframe.id.hex


def _pick_video_ext(url: str) -> str:
    """从下载地址推断扩展名，非白名单一律回落 mp4。"""
    path = (url or "").split("?", 1)[0]
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return ext if ext in VIDEO_EXTENSIONS else "mp4"


def _image_fallback_allowed(exc: Exception) -> bool:
    """仅在上游明确拒绝入参（400/413/422）时降级。

    鉴权失败、端点不存在、网络错误等与参考图无关，降级只会掩盖真实故障。
    """
    status = getattr(exc, "status_code", None)
    return status in (400, 413, 422)


def _task_fallback_allowed(task: dict) -> bool:
    """任务失败属于入参形态不兼容时，换首帧/参考图组合重试。

    DashScope 把 media 组合校验放在异步任务阶段（首帧与参考图并存），换一种
    单图形态即可成功；内容审核、超时等与入参无关，不重复提交。
    """
    code = str(task.get("code") or "")
    message = str(task.get("message") or "")
    return code.startswith("InvalidParameter") or "InvalidParameter" in message


def _image_attempts(
    first_frame_url: str | None,
    reference_urls: list[str],
    *,
    allow_text: bool,
    allow_mixed: bool = True,
) -> list[tuple[str, str | None, list[str] | None]]:
    """按可用入参生成降级尝试序列（模式, 首帧, 参考图）。

    章节生成的首帧就是本章首关键帧（同时也在参考图里），因此优先保留全部
    参考图，首帧单独提交仅作上游拒绝参考图时的降级形态。混合入参仅在协议
    支持时作为首选（聚合网关）；DashScope 原生接口的参考图不能与首帧并存。
    allow_text 由调用方显式放行（业务层仅在未请求关键帧图片时传 True），
    已有图片入参时不追加纯文生，避免成片与关键帧人物不一致。
    """
    attempts: list[tuple[str, str | None, list[str] | None]] = []
    if first_frame_url and reference_urls:
        if allow_mixed:
            attempts.append(("mixed", first_frame_url, reference_urls))
        attempts.append(("reference_only", None, reference_urls))
        attempts.append(("first_frame_only", first_frame_url, None))
    elif first_frame_url:
        attempts.append(("first_frame_only", first_frame_url, None))
    elif reference_urls:
        attempts.append(("reference_only", None, reference_urls))
    if allow_text:
        attempts.append(("text_only", None, None))
    if not attempts:
        raise RuntimeError("缺少可提交的视频图片入参")
    return attempts


def _link_attempts(
    first_frame_url: str,
    last_frame_url: str,
    *,
    allow_last: bool,
) -> list[tuple[str, str | None, str | None]]:
    """集间衔接片段的尝试序列（模式, 首帧, 尾帧）。

    尾帧不可用（旧 img_url 形态模型）时只提交首帧；尾帧提交被上游拒绝时
    降级为首帧单图，保证至少从上一集结尾画面自然起幅。
    """
    if allow_last:
        return [
            ("first_last", first_frame_url, last_frame_url),
            ("first_only", first_frame_url, None),
        ]
    return [("first_only", first_frame_url, None)]


def _is_link_row(video: StoryVideo) -> bool:
    """是否为集间衔接片段（generation_params.kind=transition）。"""
    params = video.generation_params
    return isinstance(params, dict) and params.get("kind") == LINK_KIND


def _latest_done_episodes(rows: list[StoryVideo]) -> dict[int, StoryVideo]:
    """每集最新一条已完成章节片段（排除衔接片段与非第N集分组）。"""
    picked: dict[int, StoryVideo] = {}
    for row in rows:
        if _is_link_row(row) or row.status != "done" or not row.video_file:
            continue
        episode_no = row.episode_no or 0
        if episode_no <= 0:
            continue
        current = picked.get(episode_no)
        if current is None or row.created_at > current.created_at:
            picked[episode_no] = row
    return picked


def _active_link_exists(
    rows: list[StoryVideo], from_hex: str, to_hex: str
) -> bool:
    """同一对相邻集是否已有在途衔接任务，避免重复提交。"""
    for row in rows:
        if row.status not in RUNNING_STATUSES or not _is_link_row(row):
            continue
        params = row.generation_params or {}
        if (
            params.get("transition_from_video_id") == from_hex
            and params.get("transition_to_video_id") == to_hex
        ):
            return True
    return False


def _option_str(extra: dict, key: str, default: str) -> str:
    value = extra.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else default


def _option_int(extra: dict, key: str, default: int) -> int:
    value = extra.get(key)
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _video_model_name() -> str:
    """读取 video 角色模型名；未配置时给出可操作的业务错误。"""
    try:
        return CFG.video.model_name
    except AttributeError:
        bad_except("视频模型未配置，请在「模型管理」中维护 video 角色后重试")


class VideoGenerationService:
    """视频片段生成业务层：章节片段并发生成、集间衔接、轮询与停止。"""

    def __init__(self) -> None:
        self._project_service = ProjectService()

    async def _assert_video_owned(self, session, video_id: uuid.UUID, ctx):
        """视频须存在且所属项目归当前用户。"""
        video = await VideoRepository(session).get(video_id)
        if video is None:
            bad_except("视频不存在")
        await self._project_service._assert_owned(session, video.project_id, ctx)
        return video

    def generation_options(self) -> dict:
        """生成面板需要的公共配置（不含凭证/端点等敏感信息）。"""
        try:
            extra = CFG.video.extra or {}
            model_name = CFG.video.model_name
        except AttributeError:
            extra, model_name = {}, ""
        return {
            "model": model_name,
            "resolution": _option_str(extra, "resolution", DEFAULT_RESOLUTION),
            "ratio": _option_str(extra, "ratio", DEFAULT_RATIO),
            "duration": _option_int(extra, "duration", DEFAULT_DURATION),
            "max_concurrent": MAX_CONCURRENT_VIDEO_TASKS,
            "supports_last_frame": supports_last_frame(),
        }

    @staticmethod
    async def _assert_no_running_script(session, project_id: uuid.UUID) -> None:
        """项目剧本生成进行中时不允许提交视频任务。"""
        stmt = (
            select(StoryGenerationTask.id)
            .where(
                StoryGenerationTask.project_id == project_id,
                StoryGenerationTask.task_type == StoryTaskType.SCRIPT.value,
                StoryGenerationTask.status.in_(
                    GenerationTaskRepository.RUNNING_STATUSES
                ),
            )
            .limit(1)
        )
        if await session.scalar(stmt) is not None:
            bad_except("本项目剧本生成进行中，请稍候")

    async def _merge_params(self, video_id: uuid.UUID, patch: dict) -> None:
        """读当前 generation_params 后合并写回（视频已删除时静默忽略）。"""
        async with get_session() as session:
            video = await VideoRepository(session).get(video_id)
            if video is None:
                return
            current = video.generation_params or {}
            merged = dict(current) if isinstance(current, dict) else {}
            merged.update(patch)
            await VideoRepository(session).update_fields(
                video, {"generation_params": merged}
            )
            await session.commit()

    async def _update_video(self, video_id: uuid.UUID, fields: dict) -> None:
        """短会话更新视频状态；视频已被删除时静默忽略。"""
        async with get_session() as session:
            video = await VideoRepository(session).get(video_id)
            if video is None:
                return
            await VideoRepository(session).update_fields(video, fields)
            await session.commit()

    async def _mark_generating(self, video_id: uuid.UUID) -> bool:
        """queued → generating 条件更新；已被取消/删除时不复活任务。"""
        async with get_session() as session:
            result = await session.execute(
                update(StoryVideo)
                .where(
                    StoryVideo.id == video_id,
                    StoryVideo.status == "queued",
                )
                .values(
                    status="generating",
                    error_message=None,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
            return bool(result.rowcount)

    async def _finish_video(
        self,
        video_id: uuid.UUID,
        fields: dict,
        statuses: tuple[str, ...] = ("generating",),
    ) -> bool:
        """条件更新为终态；已被用户取消时不再覆盖为 done/failed。"""
        async with get_session() as session:
            result = await session.execute(
                update(StoryVideo)
                .where(
                    StoryVideo.id == video_id,
                    StoryVideo.status.in_(statuses),
                )
                .values(**fields, updated_at=datetime.now(timezone.utc))
            )
            await session.commit()
            return bool(result.rowcount)

    @staticmethod
    def _build_inputs(
        keyframe_infos: list[dict],
        *,
        use_images: bool,
    ) -> _ChapterInputs:
        """解析参考图/首帧/封面：本章首关键帧既作首帧也保留在参考图序列。"""
        if not use_images:
            return _ChapterInputs([], None, None)
        images = [item["image_file"] for item in keyframe_infos if item["image_file"]]
        if not images:
            bad_except("本章没有可用的关键帧图片")
        return _ChapterInputs(
            reference_images=images,
            first_frame_file=images[0],
            cover_image_file=images[0],
        )

    async def generate_chapter(
        self,
        ctx,
        project_id: uuid.UUID,
        *,
        prompt: str,
        keyframe_ids: list[uuid.UUID],
        title: str | None = None,
        chapter_no: int | None = None,
        chapter_content: str | None = None,
        use_images: bool = True,
        resolution: str | None = None,
        ratio: str | None = None,
        duration: int | None = None,
    ) -> dict:
        """生成单章片段：一次提交该章全部关键帧参考图，与其它章节并行排队。"""
        if not ctx.user_id:
            bad_except("视频生成仅支持用户通道调用")

        base_prompt = _truncate(prompt or "", VIDEO_PROMPT_MAX_CHARS)
        if not base_prompt:
            bad_except("视频提示词不能为空")
        model_name = _video_model_name()

        ordered_ids = list(dict.fromkeys(keyframe_ids))
        if not ordered_ids:
            bad_except("本章没有可用的关键帧")
        episode_no = chapter_no if chapter_no is not None else 0

        async with get_session() as session:
            await self._project_service._assert_owned(session, project_id, ctx)
            await self._assert_no_running_script(session, project_id)

            by_id = await KeyframeRepository(session).get_many(ordered_ids)
            if len(by_id) != len(ordered_ids):
                bad_except("部分关键帧不存在")
            keyframes = [by_id[keyframe_id] for keyframe_id in ordered_ids]
            if any(keyframe.project_id != project_id for keyframe in keyframes):
                bad_except("部分关键帧不存在或不属于本项目")
            if any(
                keyframe.status == StoryKeyframeStatus.ARCHIVED.value
                for keyframe in keyframes
            ):
                bad_except("存在已归档关键帧，无法生成视频")

            video_repo = VideoRepository(session)
            if await video_repo.has_active_for_episode(project_id, episode_no):
                bad_except("本章片段正在生成中，请稍候")

            if use_images:
                for keyframe in keyframes:
                    image_file = keyframe.image_file
                    if not image_file or not resolve_upload_path(image_file).is_file():
                        bad_except(
                            f"关键帧「{keyframe.name or keyframe.id.hex}」图片缺失，"
                            "请先在「关键帧」面板出图后再生成"
                        )

            keyframe_infos = [
                {
                    "id": keyframe.id,
                    "script_id": keyframe.script_id,
                    "image_file": keyframe.image_file,
                    "name": _keyframe_label(keyframe),
                }
                for keyframe in keyframes
            ]

        inputs = self._build_inputs(
            keyframe_infos,
            use_images=use_images,
        )
        final_prompt = base_prompt

        final_title = (title or "").strip() or (
            f"第{chapter_no}集" if chapter_no is not None else "未匹配章节片段"
        )
        params = {
            "chapter_no": chapter_no,
            "chapter_title": final_title,
            "chapter_content": _truncate(chapter_content or "", CHAPTER_CONTENT_MAX)
            or None,
            "keyframe_ids": [item["id"].hex for item in keyframe_infos],
            "reference_images": inputs.reference_images,
            "use_images": bool(use_images),
            "first_frame_file": inputs.first_frame_file,
            "resolution": resolution,
            "ratio": ratio,
            "duration": duration,
        }

        async with _project_task_lock(project_id.hex):
            async with get_session() as session:
                video_repo = VideoRepository(session)
                if await video_repo.has_active_for_episode(project_id, episode_no):
                    bad_except("本章片段正在生成中，请稍候")
                video = await video_repo.create(
                    video_id=uuid7(),
                    project_id=project_id,
                    keyframe_id=keyframe_infos[0]["id"],
                    script_id=keyframe_infos[0]["script_id"],
                    source="generated",
                    title=final_title,
                    episode_no=episode_no,
                    status="queued",
                    provider="video",
                    model=model_name,
                    prompt=final_prompt,
                    generation_params=params,
                    target_platform="AI 生成",
                )
                project = await ProjectRepository(session).get(project_id)
                await ProjectRepository(session).recount_assets(project)
                await session.commit()
                data = video.to_dict()
                video_id = video.id
                primary_keyframe_id = keyframe_infos[0]["id"]

        self._spawn_video_task(
            video_id,
            self._execute_video(
                video_id=video_id,
                project_id=project_id,
                keyframe_id=primary_keyframe_id,
                prompt=final_prompt,
                negative_prompt=None,
                params=params,
                first_frame_file=inputs.first_frame_file,
                reference_image_files=inputs.reference_images,
                cover_image_file=inputs.cover_image_file,
                send_references=bool(use_images),
            ),
        )
        logger.info(
            f"[STORY] 章节视频任务已创建 project={project_id.hex} "
            f"chapter={chapter_no} keyframes={len(keyframe_infos)} "
            f"references={len(inputs.reference_images)}"
        )
        return data

    def _spawn_video_task(self, video_id: uuid.UUID, coro) -> None:
        """登记单章生成任务，完成时清理注册表映射。"""
        task = asyncio.create_task(coro)
        _video_tasks[video_id.hex] = task
        task.add_done_callback(
            lambda done, vid=video_id.hex: (
                _video_tasks.pop(vid, None) if _video_tasks.get(vid) is done else None
            )
        )

    async def _execute_video(
        self,
        video_id: uuid.UUID,
        project_id: uuid.UUID,
        keyframe_id: uuid.UUID,
        prompt: str,
        negative_prompt: str | None,
        params: dict,
        first_frame_file: str | None,
        reference_image_files: list[str] | None = None,
        cover_image_file: str | None = None,
        send_references: bool = True,
    ) -> bool:
        """后台执行一个片段：排队 → 提交（参考图或首帧）→ 轮询 → 下载 → 封面。

        成功返回 True；失败置 failed 返回 False；取消置 cancelled 后继续抛出
        CancelledError。
        """
        semaphore = _project_semaphore(project_id.hex)
        video_rel: str | None = None
        cover_rel: str | None = None
        task_id: str | None = None
        used_mode = "text_only"
        try:
            async with semaphore:
                if not await self._mark_generating(video_id):
                    logger.info(
                        f"[STORY] 视频任务已被取消或删除，跳过执行 video={video_id.hex}"
                    )
                    return False

                first_frame_url: str | None = None
                reference_urls: list[str] = []
                if send_references:
                    if first_frame_file:
                        first_frame_url = await asyncio.to_thread(
                            image_to_reference_data_uri, first_frame_file
                        )
                    if reference_image_files:
                        reference_urls = [
                            await asyncio.to_thread(image_to_reference_data_uri, file)
                            for file in reference_image_files
                        ]

                attempts = [
                    (
                        mode,
                        {
                            "first_frame_url": frame_url,
                            "reference_image_urls": image_urls,
                        },
                    )
                    for mode, frame_url, image_urls in _image_attempts(
                        first_frame_url,
                        reference_urls,
                        allow_text=not send_references,
                        allow_mixed=supports_mixed_media(),
                    )
                ]
                task, used_mode = await self._submit_with_fallback(
                    video_id,
                    prompt,
                    params,
                    attempts,
                    negative_prompt=negative_prompt,
                    task_label="视频生成",
                )
                video_url = task.get("video_url") or ""
                if not video_url:
                    raise RuntimeError("视频生成成功但未返回视频地址")

                video_rel, file_size = await self._download(video_id, video_url)
                meta = await asyncio.to_thread(
                    probe_video_meta, resolve_upload_path(video_rel)
                )
                cover_rel = await self._make_cover(
                    video_id, cover_image_file, video_rel
                )
                finished = await self._finish_video(
                    video_id,
                    {
                        "status": "done",
                        "video_file": video_rel,
                        "cover_file": cover_rel,
                        "file_size": file_size,
                        "error_message": None,
                        **meta,
                    },
                )
                if not finished:
                    logger.warning(
                        f"[STORY] 视频已完成但已被中止/删除，丢弃结果 video={video_id.hex}"
                    )
                    await asyncio.to_thread(unlink_quietly, video_rel)
                    if cover_rel:
                        await asyncio.to_thread(unlink_quietly, cover_rel)
                    return False
                logger.info(
                    f"[STORY] 视频生成完成 video={video_id.hex} "
                    f"keyframe={keyframe_id.hex} file={video_rel} "
                    f"image_mode={used_mode}"
                )
                return True
        except asyncio.CancelledError:
            logger.warning(f"[STORY] 视频生成被取消 video={video_id.hex}")
            await _cancel_remote_task(task_id)
            await self._update_video(
                video_id,
                {"status": "cancelled", "error_message": "用户主动中止生成"},
            )
            if video_rel:
                await asyncio.to_thread(unlink_quietly, video_rel)
            if cover_rel:
                await asyncio.to_thread(unlink_quietly, cover_rel)
            raise
        except Exception as exc:
            logger.error(f"[STORY] 视频生成失败 video={video_id.hex}: {exc}")
            await self._finish_video(
                video_id,
                {"status": "failed", "error_message": str(exc)[:500]},
                statuses=("queued", "generating"),
            )
            if video_rel:
                await asyncio.to_thread(unlink_quietly, video_rel)
            if cover_rel:
                await asyncio.to_thread(unlink_quietly, cover_rel)
            return False

    async def _submit_with_fallback(
        self,
        video_id: uuid.UUID,
        prompt: str,
        params: dict,
        attempts: list[tuple[str, dict]],
        *,
        negative_prompt: str | None = None,
        task_label: str,
    ) -> tuple[dict, str]:
        """按图片入参形态逐级降级提交并等待任务，返回 (成功任务, 实际形态)。

        提交被拒（400/413/422）或任务阶段 InvalidParameter 时才换下一种图片形态；
        鉴权、网络、内容审核等与入参无关的失败直接抛出，避免掩盖真实故障。
        """
        for index, (mode, image_kwargs) in enumerate(attempts):
            has_next = index + 1 < len(attempts)
            try:
                task_id = await asyncio.to_thread(
                    submit_video,
                    prompt,
                    params.get("resolution"),
                    params.get("ratio"),
                    params.get("duration"),
                    negative_prompt=negative_prompt,
                    **image_kwargs,
                )
            except Exception as exc:
                if not has_next or not _image_fallback_allowed(exc):
                    raise
                logger.warning(
                    f"[STORY] {task_label}图片入参被拒绝，降级重试 "
                    f"video={video_id.hex} {mode} -> {attempts[index + 1][0]}: {exc}"
                )
                continue
            await self._merge_params(
                video_id, {"image_mode": mode, "image_fallback": index > 0}
            )
            await self._update_video(video_id, {"external_task_id": task_id})
            task = await self._wait_task(task_id)
            if task["task_status"] == "SUCCEEDED":
                return task, mode
            if has_next and _task_fallback_allowed(task):
                logger.warning(
                    f"[STORY] {task_label}任务因入参不兼容失败，换图片形态重试 "
                    f"video={video_id.hex} {mode} -> {attempts[index + 1][0]}: "
                    f"code={task['code']} message={task['message']}"
                )
                continue
            raise RuntimeError(
                f"{task_label}失败: status={task['task_status']}, "
                f"code={task['code']}, message={task['message']}"
            )
        raise RuntimeError(f"{task_label}失败: 未能提交可用的生成任务")

    async def _wait_task(self, task_id: str) -> dict:
        """异步轮询上游任务直到终态；sleep 期间可被 stop 取消。"""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + VIDEO_WAIT_TIMEOUT
        while True:
            task = await asyncio.to_thread(get_video_task, task_id)
            if task["task_status"] in TERMINAL_STATUSES:
                return task
            if loop.time() >= deadline:
                raise TimeoutError(
                    f"视频生成任务超时（{VIDEO_WAIT_TIMEOUT:.0f}s, task_id={task_id}）"
                )
            await asyncio.sleep(VIDEO_POLL_INTERVAL)

    async def _download(self, video_id: uuid.UUID, url: str) -> tuple[str, int]:
        """流式下载生成结果到本地，返回 (相对路径, 字节数)。"""
        ext = _pick_video_ext(url)
        relative = f"{VIDEO_SUBDIR}/{uuid7().hex}.{ext}"
        target = ENV.upload_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        max_bytes = GENERATED_VIDEO_MAX_MB * 1024 * 1024
        total = 0
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(300.0, connect=30.0), follow_redirects=True
            ) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with open(part, "wb") as handle:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            total += len(chunk)
                            if total > max_bytes:
                                raise RuntimeError(
                                    f"生成视频超过下载上限（{GENERATED_VIDEO_MAX_MB}MB）"
                                )
                            handle.write(chunk)
            part.replace(target)
            return relative, total
        except BaseException:
            # CancelledError 继承 BaseException，取消下载时同样要清理半成品
            part.unlink(missing_ok=True)
            raise

    async def _make_cover(
        self,
        video_id: uuid.UUID,
        cover_image_file: str | None,
        video_rel: str,
    ) -> str | None:
        """封面优先复用显式传入的图片（章节首关键帧 / 衔接片段首帧），
        缺失时抽取视频首帧。"""
        if cover_image_file:
            target: Path | None = None
            try:
                source = resolve_upload_path(cover_image_file)
                ext = source.suffix.lstrip(".").lower() or "webp"
                relative = f"{COVER_SUBDIR}/{uuid7().hex}.{ext}"
                target = ENV.upload_dir / relative

                def _copy() -> None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)

                await asyncio.to_thread(_copy)
                return relative
            except asyncio.CancelledError:
                if target:
                    target.unlink(missing_ok=True)
                raise
            except Exception as exc:
                if target:
                    target.unlink(missing_ok=True)
                logger.warning(
                    f"[STORY] 复用关键帧封面失败 video={video_id.hex}: {exc}"
                )

        relative = f"{COVER_SUBDIR}/{uuid7().hex}.jpg"
        target = ENV.upload_dir / relative

        def _extract() -> bool:
            target.parent.mkdir(parents=True, exist_ok=True)
            return extract_first_frame(resolve_upload_path(video_rel), target)

        ok = await asyncio.to_thread(_extract)
        if not ok:
            target.unlink(missing_ok=True)
        return relative if ok else None

    # —— 关联集：相邻两集首尾帧衔接片段 ——

    @staticmethod
    def _link_view(video: StoryVideo) -> dict:
        """衔接片段视图：在视频字段上附加衔接对信息。"""
        data = video.to_dict()
        params = video.generation_params or {}
        data["from_video_id"] = params.get("transition_from_video_id")
        data["to_video_id"] = params.get("transition_to_video_id")
        data["from_episode_no"] = params.get("from_episode_no")
        data["to_episode_no"] = params.get("to_episode_no")
        return data

    async def list_links(self, ctx, project_id: uuid.UUID) -> dict:
        """关联集视图：每集最新一条已完成片段 + 全部集间衔接片段。"""
        if not ctx.user_id:
            bad_except("视频操作仅支持用户通道调用")
        async with get_session() as session:
            await self._project_service._assert_owned(session, project_id, ctx)
            rows = await VideoRepository(session).list_generated(project_id)

        episodes = _latest_done_episodes(rows)
        # 只展示引用仍存在的章节片段的衔接（历史删除残留不再暴露）
        episode_ids = {
            row.id.hex for row in rows if not _is_link_row(row)
        }
        links = [
            row
            for row in rows
            if _is_link_row(row)
            and (row.generation_params or {}).get("transition_from_video_id")
            in episode_ids
            and (row.generation_params or {}).get("transition_to_video_id")
            in episode_ids
        ]
        return {
            "episodes": [
                video.to_dict()
                for _, video in sorted(episodes.items(), key=lambda item: item[0])
            ],
            "links": [self._link_view(video) for video in links],
        }

    async def create_link(
        self,
        ctx,
        project_id: uuid.UUID,
        *,
        from_video_id: uuid.UUID,
        to_video_id: uuid.UUID,
        prompt: str | None = None,
        resolution: str | None = None,
        ratio: str | None = None,
        duration: int | None = None,
    ) -> dict:
        """生成集间衔接片段：上一集成片尾帧作首帧、下一集成片首帧作尾帧。"""
        if not ctx.user_id:
            bad_except("视频操作仅支持用户通道调用")
        if from_video_id == to_video_id:
            bad_except("请选择相邻两集的片段")
        model_name = _video_model_name()
        final_prompt = _truncate(
            (prompt or "").strip() or LINK_PROMPT_DEFAULT,
            VIDEO_PROMPT_MAX_CHARS,
        )

        async with get_session() as session:
            await self._project_service._assert_owned(session, project_id, ctx)
            await self._assert_no_running_script(session, project_id)
            video_repo = VideoRepository(session)
            from_video = await video_repo.get(from_video_id)
            to_video = await video_repo.get(to_video_id)
            for video in (from_video, to_video):
                if video is None or video.project_id != project_id:
                    bad_except("选择的片段不存在或不属于本项目")
                if _is_link_row(video):
                    bad_except("衔接片段不能再次作为衔接输入")
                if (
                    video.source != "generated"
                    or video.status != "done"
                    or not video.video_file
                ):
                    bad_except("请先完成相邻两集片段的生成")
            from_episode = from_video.episode_no or 0
            to_episode = to_video.episode_no or 0
            if from_episode <= 0 or to_episode <= from_episode:
                bad_except("衔接方向应为上一集 → 下一集")
            rows = await video_repo.list_generated(project_id)
            done_episodes = sorted(_latest_done_episodes(rows))
            if (
                from_episode not in done_episodes
                or to_episode not in done_episodes
                or done_episodes.index(to_episode)
                != done_episodes.index(from_episode) + 1
            ):
                bad_except("仅支持相邻两集片段生成衔接")
            if _active_link_exists(rows, from_video_id.hex, to_video_id.hex):
                bad_except("该衔接片段正在生成中，请稍候")
            from_file = from_video.video_file
            to_file = to_video.video_file

        link_id = uuid7()
        first_rel = f"{LINK_FRAME_SUBDIR}/{link_id.hex}-first.jpg"
        last_rel = f"{LINK_FRAME_SUBDIR}/{link_id.hex}-last.jpg"
        first_path = resolve_upload_path(first_rel)
        last_path = resolve_upload_path(last_rel)
        first_path.parent.mkdir(parents=True, exist_ok=True)
        ok_first = await asyncio.to_thread(
            extract_last_frame, resolve_upload_path(from_file), first_path
        )
        ok_last = await asyncio.to_thread(
            extract_first_frame, resolve_upload_path(to_file), last_path
        )
        if not (ok_first and ok_last):
            first_path.unlink(missing_ok=True)
            last_path.unlink(missing_ok=True)
            bad_except(
                "抽取上一集尾帧或下一集首帧失败，请确认片段可解析且 ffmpeg 可用"
            )

        title = f"第{from_episode}→{to_episode}集衔接"
        params = {
            "kind": LINK_KIND,
            "transition_from_video_id": from_video_id.hex,
            "transition_to_video_id": to_video_id.hex,
            "from_episode_no": from_episode,
            "to_episode_no": to_episode,
            "first_frame_file": first_rel,
            "last_frame_file": last_rel,
            "resolution": resolution,
            "ratio": ratio,
            "duration": duration,
        }
        stale_files: list[str] = []
        try:
            async with _project_task_lock(project_id.hex):
                async with get_session() as session:
                    video_repo = VideoRepository(session)
                    rows = await video_repo.list_generated(project_id)
                    if _active_link_exists(rows, from_video_id.hex, to_video_id.hex):
                        bad_except("该衔接片段正在生成中，请稍候")
                    # 同一衔接位重新生成时替换旧版本，避免不可见的残留行与文件
                    for row in rows:
                        if not _is_link_row(row):
                            continue
                        row_params = row.generation_params or {}
                        if (
                            row_params.get("transition_from_video_id")
                            != from_video_id.hex
                            or row_params.get("transition_to_video_id")
                            != to_video_id.hex
                        ):
                            continue
                        stale_files.extend(video_local_files(row))
                        await video_repo.delete(row)
                    video = await video_repo.create(
                        video_id=link_id,
                        project_id=project_id,
                        source="generated",
                        title=title,
                        episode_no=from_episode,
                        status="queued",
                        provider="video",
                        model=model_name,
                        prompt=final_prompt,
                        generation_params=params,
                        target_platform="AI 生成",
                    )
                    project = await ProjectRepository(session).get(project_id)
                    await ProjectRepository(session).recount_assets(project)
                    await session.commit()
                    data = self._link_view(video)
        except BaseException:
            first_path.unlink(missing_ok=True)
            last_path.unlink(missing_ok=True)
            raise

        if stale_files:
            await asyncio.to_thread(
                lambda: [unlink_quietly(path) for path in stale_files]
            )

        self._spawn_video_task(
            link_id,
            self._execute_link(
                video_id=link_id,
                project_id=project_id,
                prompt=final_prompt,
                params=params,
                first_frame_file=first_rel,
                last_frame_file=last_rel,
            ),
        )
        logger.info(
            f"[STORY] 集间衔接任务已创建 project={project_id.hex} "
            f"episode={from_episode}->{to_episode} video={link_id.hex}"
        )
        return data

    async def _execute_link(
        self,
        video_id: uuid.UUID,
        project_id: uuid.UUID,
        prompt: str,
        params: dict,
        first_frame_file: str,
        last_frame_file: str,
    ) -> bool:
        """后台执行衔接片段：提交首尾帧 → 轮询 → 下载 → 封面。"""
        semaphore = _project_semaphore(project_id.hex)
        video_rel: str | None = None
        cover_rel: str | None = None
        task_id: str | None = None
        used_mode = "first_last"
        try:
            async with semaphore:
                if not await self._mark_generating(video_id):
                    logger.info(
                        f"[STORY] 衔接任务已被取消或删除，跳过执行 video={video_id.hex}"
                    )
                    return False

                first_uri = await asyncio.to_thread(
                    image_to_reference_data_uri, first_frame_file
                )
                last_uri = await asyncio.to_thread(
                    image_to_reference_data_uri, last_frame_file
                )
                attempts = [
                    (
                        mode,
                        {"first_frame_url": frame_url, "last_frame_url": last_url},
                    )
                    for mode, frame_url, last_url in _link_attempts(
                        first_uri,
                        last_uri,
                        allow_last=supports_last_frame(),
                    )
                ]
                task, used_mode = await self._submit_with_fallback(
                    video_id,
                    prompt,
                    params,
                    attempts,
                    task_label="衔接片段生成",
                )
                video_url = task.get("video_url") or ""
                if not video_url:
                    raise RuntimeError("衔接片段生成成功但未返回视频地址")

                video_rel, file_size = await self._download(video_id, video_url)
                meta = await asyncio.to_thread(
                    probe_video_meta, resolve_upload_path(video_rel)
                )
                cover_rel = await self._make_cover(
                    video_id, first_frame_file, video_rel
                )
                finished = await self._finish_video(
                    video_id,
                    {
                        "status": "done",
                        "video_file": video_rel,
                        "cover_file": cover_rel,
                        "file_size": file_size,
                        "error_message": None,
                        **meta,
                    },
                )
                if not finished:
                    logger.warning(
                        f"[STORY] 衔接片段已完成但已被中止/删除，丢弃结果 "
                        f"video={video_id.hex}"
                    )
                    await asyncio.to_thread(unlink_quietly, video_rel)
                    if cover_rel:
                        await asyncio.to_thread(unlink_quietly, cover_rel)
                    return False
                logger.info(
                    f"[STORY] 集间衔接片段完成 video={video_id.hex} "
                    f"file={video_rel} image_mode={used_mode}"
                )
                return True
        except asyncio.CancelledError:
            logger.warning(f"[STORY] 衔接片段生成被取消 video={video_id.hex}")
            await _cancel_remote_task(task_id)
            await self._update_video(
                video_id,
                {"status": "cancelled", "error_message": "用户主动中止生成"},
            )
            if video_rel:
                await asyncio.to_thread(unlink_quietly, video_rel)
            if cover_rel:
                await asyncio.to_thread(unlink_quietly, cover_rel)
            raise
        except Exception as exc:
            logger.error(f"[STORY] 衔接片段生成失败 video={video_id.hex}: {exc}")
            await self._finish_video(
                video_id,
                {"status": "failed", "error_message": str(exc)[:500]},
                statuses=("queued", "generating"),
            )
            if video_rel:
                await asyncio.to_thread(unlink_quietly, video_rel)
            if cover_rel:
                await asyncio.to_thread(unlink_quietly, cover_rel)
            return False

    async def stop(self, ctx, video_id: uuid.UUID) -> bool:
        """中止在途生成/合成任务（内存任务取消 + 上游 cancel + 状态终态化）。"""
        if not ctx.user_id:
            bad_except("视频操作仅支持用户通道调用")
        cancelled = False
        remote_task_id: str | None = None
        async with get_session() as session:
            video = await self._assert_video_owned(session, video_id, ctx)
            task = _video_tasks.get(video_id.hex)
            if task and not task.done():
                task.cancel()
                cancelled = True
            # 条件更新：后台任务若已完成并写入 done，不再回写成 cancelled
            result = await session.execute(
                update(StoryVideo)
                .where(
                    StoryVideo.id == video_id,
                    StoryVideo.status.in_(RUNNING_STATUSES),
                )
                .values(
                    status="cancelled",
                    error_message="用户主动中止生成",
                    updated_at=datetime.now(timezone.utc),
                )
            )
            if result.rowcount:
                remote_task_id = video.external_task_id
                cancelled = True
            await session.commit()
        await _cancel_remote_task(remote_task_id)
        return cancelled

    async def stop_all(self, ctx, project_id: uuid.UUID) -> int:
        """中止项目下全部在途视频生成/合成任务。"""
        if not ctx.user_id:
            bad_except("视频操作仅支持用户通道调用")
        stopped = 0
        remote_task_ids: list[str] = []
        async with get_session() as session:
            await self._project_service._assert_owned(session, project_id, ctx)
            stmt = select(StoryVideo).where(
                StoryVideo.project_id == project_id,
                StoryVideo.status.in_(RUNNING_STATUSES),
            )
            rows = list((await session.scalars(stmt)).all())
            for row in rows:
                result = await session.execute(
                    update(StoryVideo)
                    .where(
                        StoryVideo.id == row.id,
                        StoryVideo.status.in_(RUNNING_STATUSES),
                    )
                    .values(
                        status="cancelled",
                        error_message="用户主动中止生成",
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                if not result.rowcount:
                    continue
                task = _video_tasks.get(row.id.hex)
                if task and not task.done():
                    task.cancel()
                if row.external_task_id:
                    remote_task_ids.append(row.external_task_id)
                stopped += 1
            await session.commit()
        if remote_task_ids:
            await asyncio.gather(
                *(_cancel_remote_task(task_id) for task_id in remote_task_ids)
            )
        logger.info(
            f"[STORY] 项目视频任务已全部中止 project={project_id.hex} count={stopped}"
        )
        return stopped
