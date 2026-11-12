"""
剧本模块视频片段生成业务层：单章生成与章节串行衔接。

- 单章生成：一次提交该章全部关键帧参考图，产出一个片段；开启衔接时自动
  取上一集最近一条已完成片段的尾帧作为本章首帧。
- 串行链：按集顺序逐章生成，第 N 章完成后抽取成片最后一帧，作为第 N+1
  章首帧，保证集间画面连续；任一章失败/中止即终止整链，后续标记为取消。
- 链首使用本章第一个关键帧作首帧，参考图保留本章全部关键帧（含复用为首
  帧的那张），避免改写编排提示词中已生成的【图k】编号。
- 关键帧本地图片压缩后转 base64 data URI 作为参考图/首帧（DashScope 原生
  协议 wan3.0 走 media、旧模型走 img_url；聚合网关协议走 content 数组的
  first_frame / reference_image 角色）；首帧与参考图可同时下发，上游拒绝
  时按 mixed → 单图保底 → 纯文生阶梯降级（衔接章节优先保留首帧，链首优先
  保留参考图；串行链不回退纯文生，避免画面断层）。
- 任务生命周期：queued → generating → done / failed / cancelled。后台协程
  异步轮询上游任务（等待期间可取消），完成后立即下载落盘，封面优先复用
  本章首关键帧图片，失败再抽视频首帧。
- 项目级并发上限 MAX_CONCURRENT_VIDEO_TASKS；串行链同一时刻只跑一章，
  其他项目不受影响。
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
)
from service.story.project import ProjectService
from service.story.storage import (
    image_to_reference_data_uri,
    resolve_upload_path,
    unlink_quietly,
)
from service.story.video import (
    COVER_SUBDIR,
    FRAME_SUBDIR,
    VIDEO_EXTENSIONS,
    VIDEO_SUBDIR,
    extract_first_frame,
    extract_last_frame,
    probe_video_meta,
)
from utils.env import ENV
from utils.logger import logger

# 项目级视频生成并发上限：视频合成单次成本高、耗时长，保持 queued 排队更稳
MAX_CONCURRENT_VIDEO_TASKS = 3

# 串行链一次最多章节数，避免误操作提交超长链
MAX_CHAIN_CHAPTERS = 50

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

# 串行衔接提示：放在整章提示词最前，再统一截断，避免被尾部截掉
CHAIN_LINK_NOTE = (
    "衔接要求：本片段首帧为上一章片段的结尾画面，请从该画面无缝开始，"
    "保持人物、服装、场景、光线与镜头方向一致，再自然推进本章剧情。"
)

# 运行期任务注册表：video_id_hex -> asyncio.Task；项目信号量按需创建
_video_tasks: dict[str, asyncio.Task] = {}
_project_semaphores: dict[str, asyncio.Semaphore] = {}
# 单章/串行链启动互斥锁：串行化"校验 + 建行"窗口，避免两条任务同时落库
_project_task_locks: dict[str, asyncio.Lock] = {}
# 串行链注册表：project_hex -> 链状态（结束后保留摘要，下次启动替换）
_chains: dict[str, "_ChainState"] = {}


@dataclass
class _ChapterInputs:
    """单章提交前解析出的图片入参。"""

    reference_images: list[str]
    first_frame_file: str | None
    cover_image_file: str | None
    first_frame_source: str
    link_degraded: bool
    prev_video_id: str | None


@dataclass
class _ChainEntry:
    """串行链中一个章节的执行快照（不持有 ORM 对象）。"""

    video_id: uuid.UUID
    keyframe_id: uuid.UUID
    script_id: uuid.UUID | None
    base_prompt: str
    chapter_no: int | None
    title: str
    params: dict
    reference_images: list[str]
    cover_image_file: str | None
    first_keyframe_image: str | None


@dataclass
class _ChainState:
    """串行链内存状态；running 覆盖"已登记但协程尚未启动"的窗口。"""

    chain_id: str
    project_id: uuid.UUID
    chapters: list[dict]
    task: asyncio.Task | None = None
    cursor: int = 0
    cancel_requested: bool = False
    starting: bool = True

    @property
    def running(self) -> bool:
        return self.starting or (self.task is not None and not self.task.done())


def _project_semaphore(project_hex: str) -> asyncio.Semaphore:
    """获取项目级视频生成信号量（懒创建，同一事件循环内复用）。"""
    semaphore = _project_semaphores.get(project_hex)
    if semaphore is None:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_VIDEO_TASKS)
        _project_semaphores[project_hex] = semaphore
    return semaphore


def _project_task_lock(project_hex: str) -> asyncio.Lock:
    """获取项目级启动锁（懒创建），串行化单章/链的建行窗口。"""
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


def cancel_chain(project_hex: str) -> bool:
    """请求中止项目串行链；当前章节的 CancelledError 由链任务统一收尾。"""
    state = _chains.get(project_hex)
    if state is None or not state.running:
        return False
    state.cancel_requested = True
    if state.task is not None and not state.task.done():
        state.task.cancel()
    return True


def cancel_chain_for_video(video_id: uuid.UUID) -> bool:
    """视频属于活跃串行链时中止整链（删除/单独停止链内章节）。"""
    for state in list(_chains.values()):
        if not state.running:
            continue
        if any(chapter["video_id"] == video_id.hex for chapter in state.chapters):
            return cancel_chain(state.project_id.hex)
    return False


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


def _with_chain_note(prompt: str) -> str:
    """整章提示词前追加串行衔接说明，再统一截断到上限。"""
    return _truncate(f"{CHAIN_LINK_NOTE}\n\n{prompt}", VIDEO_PROMPT_MAX_CHARS)


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


def _image_attempts(
    first_frame_url: str | None,
    reference_urls: list[str],
    *,
    allow_text: bool,
    prefer_first_frame: bool = True,
) -> list[tuple[str, str | None, list[str] | None]]:
    """按可用入参生成降级尝试序列（模式, 首帧, 参考图）。

    衔接章节优先保留上一章尾帧（断点续接优先）；链首/无衔接章节的首帧就是
    本章关键帧，降级时优先保留参考图。串行链关闭纯文生兜底。
    """
    attempts: list[tuple[str, str | None, list[str] | None]] = []
    if first_frame_url and reference_urls:
        attempts.append(("mixed", first_frame_url, reference_urls))
        if prefer_first_frame:
            attempts.append(("first_frame_only", first_frame_url, None))
            attempts.append(("reference_only", None, reference_urls))
        else:
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
    """视频片段生成业务层：项目属主校验收口，单章生成/串行链/轮询/下载。"""

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

    async def _video_snapshot(self, video_id: uuid.UUID) -> dict | None:
        """短会话读取视频执行快照，避免长事务持有连接。"""
        async with get_session() as session:
            video = await VideoRepository(session).get(video_id)
            if video is None:
                return None
            params = video.generation_params or {}
            return {
                "id": video.id,
                "status": video.status,
                "video_file": video.video_file,
                "params": dict(params) if isinstance(params, dict) else {},
            }

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

    async def _ensure_tail_frame(self, snapshot: dict) -> str | None:
        """获取视频成片尾帧相对路径；缺失时抽取并缓存到 generation_params。"""
        tail_frame = snapshot["params"].get("tail_frame_file")
        if tail_frame and resolve_upload_path(tail_frame).is_file():
            return tail_frame
        video_file = snapshot.get("video_file")
        if not video_file:
            return None
        relative = f"{FRAME_SUBDIR}/{snapshot['id'].hex}.jpg"
        ok = await asyncio.to_thread(
            extract_last_frame,
            resolve_upload_path(video_file),
            resolve_upload_path(relative),
        )
        if not ok:
            logger.warning(f"[STORY] 尾帧抽取失败，衔接降级 video={snapshot['id'].hex}")
            return None
        await self._merge_params(snapshot["id"], {"tail_frame_file": relative})
        snapshot["params"]["tail_frame_file"] = relative
        return relative

    async def _build_inputs(
        self,
        keyframe_infos: list[dict],
        *,
        use_images: bool,
        link_previous: bool,
        prev_snapshot: dict | None,
    ) -> _ChapterInputs:
        """解析首帧/参考图/封面：优先上一章尾帧，其次本章首关键帧。"""
        images = [item["image_file"] for item in keyframe_infos if item["image_file"]]
        if not use_images:
            return _ChapterInputs([], None, None, "none", False, None)

        first_frame_file: str | None = None
        first_frame_source = "own_first_keyframe"
        link_degraded = False
        prev_video_id = prev_snapshot["id"].hex if prev_snapshot else None
        if link_previous and prev_snapshot is not None:
            tail_frame = await self._ensure_tail_frame(prev_snapshot)
            if tail_frame:
                first_frame_file = tail_frame
                first_frame_source = "prev_tail"
            else:
                link_degraded = True
        if first_frame_file is None and images:
            first_frame_file = images[0]
        cover_image_file = images[0] if images else first_frame_file
        return _ChapterInputs(
            reference_images=images,
            first_frame_file=first_frame_file,
            cover_image_file=cover_image_file,
            first_frame_source=first_frame_source,
            link_degraded=link_degraded,
            prev_video_id=prev_video_id,
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
        link_previous: bool = True,
    ) -> dict:
        """生成单章片段；link_previous 开启时自动衔接上一集已完成片段尾帧。"""
        if not ctx.user_id:
            bad_except("视频生成仅支持用户通道调用")
        chain_state = _chains.get(project_id.hex)
        if chain_state is not None and chain_state.running:
            bad_except("本项目串行生成任务进行中，请稍候")

        base_prompt = _truncate(prompt or "", VIDEO_PROMPT_MAX_CHARS)
        if not base_prompt:
            bad_except("视频提示词不能为空")
        model_name = _video_model_name()

        ordered_ids = list(dict.fromkeys(keyframe_ids))
        if not ordered_ids:
            bad_except("本章没有可用的关键帧")
        episode_no = chapter_no if chapter_no is not None else 0

        prev_snapshot: dict | None = None
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

            if use_images and link_previous and episode_no > 1:
                prev_video = await video_repo.get_latest_done_before(
                    project_id, episode_no
                )
                if prev_video is not None:
                    prev_params = prev_video.generation_params or {}
                    prev_snapshot = {
                        "id": prev_video.id,
                        "status": prev_video.status,
                        "video_file": prev_video.video_file,
                        "params": (
                            dict(prev_params) if isinstance(prev_params, dict) else {}
                        ),
                    }

            keyframe_infos = [
                {
                    "id": keyframe.id,
                    "script_id": keyframe.script_id,
                    "image_file": keyframe.image_file,
                    "name": _keyframe_label(keyframe),
                }
                for keyframe in keyframes
            ]

        inputs = await self._build_inputs(
            keyframe_infos,
            use_images=use_images,
            link_previous=link_previous,
            prev_snapshot=prev_snapshot,
        )
        final_prompt = (
            _with_chain_note(base_prompt)
            if inputs.first_frame_source == "prev_tail"
            else base_prompt
        )

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
            "first_frame_source": inputs.first_frame_source,
            "first_frame_file": inputs.first_frame_file,
            "prev_video_id": inputs.prev_video_id,
            "link_degraded": inputs.link_degraded,
            "resolution": resolution,
            "ratio": ratio,
            "duration": duration,
            "chain_id": None,
        }

        async with _project_task_lock(project_id.hex):
            async with get_session() as session:
                video_repo = VideoRepository(session)
                chain_state = _chains.get(project_id.hex)
                if chain_state is not None and chain_state.running:
                    bad_except("本项目串行生成任务进行中，请稍候")
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
                chain_mode=False,
                prefer_first_frame=inputs.first_frame_source == "prev_tail",
            ),
        )
        logger.info(
            f"[STORY] 章节视频任务已创建 project={project_id.hex} "
            f"chapter={chapter_no} keyframes={len(keyframe_infos)} "
            f"references={len(inputs.reference_images)} "
            f"first_frame={inputs.first_frame_source}"
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
        chain_mode: bool = False,
        prefer_first_frame: bool = True,
    ) -> bool:
        """后台执行一个片段：排队 → 提交（首帧+多参考图）→ 轮询 → 下载 → 封面。

        成功返回 True；失败置 failed 返回 False；取消置 cancelled 后继续抛出
        CancelledError，由串行链统一收尾。
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

                attempts = _image_attempts(
                    first_frame_url,
                    reference_urls,
                    allow_text=not chain_mode,
                    prefer_first_frame=prefer_first_frame,
                )
                for index, (mode, frame_url, image_urls) in enumerate(attempts):
                    try:
                        task_id = await asyncio.to_thread(
                            submit_video,
                            prompt,
                            params.get("resolution"),
                            params.get("ratio"),
                            params.get("duration"),
                            first_frame_url=frame_url,
                            reference_image_urls=image_urls,
                            negative_prompt=negative_prompt,
                        )
                        used_mode = mode
                        await self._merge_params(
                            video_id,
                            {
                                "image_mode": mode,
                                "image_fallback": index > 0,
                            },
                        )
                        break
                    except Exception as exc:
                        if index == len(attempts) - 1 or not _image_fallback_allowed(
                            exc
                        ):
                            raise
                        logger.warning(
                            f"[STORY] 视频图片入参被拒绝，降级重试 video={video_id.hex} "
                            f"{mode} -> {attempts[index + 1][0]}: {exc}"
                        )

                await self._update_video(video_id, {"external_task_id": task_id})
                task = await self._wait_task(task_id)
                if (
                    task["task_status"] != "SUCCEEDED"
                    and (first_frame_url or reference_urls)
                    and not chain_mode
                ):
                    # 单章模式保留一次文生兜底；串行链直接失败，避免画面断层
                    logger.warning(
                        f"[STORY] 参考图视频任务失败，回退文生视频重试 video={video_id.hex}: "
                        f"status={task['task_status']} code={task['code']} message={task['message']}"
                    )
                    task_id = await asyncio.to_thread(
                        submit_video,
                        prompt,
                        params.get("resolution"),
                        params.get("ratio"),
                        params.get("duration"),
                        negative_prompt=negative_prompt,
                    )
                    used_mode = "text_only"
                    await self._update_video(video_id, {"external_task_id": task_id})
                    await self._merge_params(
                        video_id,
                        {"image_mode": "text_only", "image_fallback": True},
                    )
                    task = await self._wait_task(task_id)
                if task["task_status"] != "SUCCEEDED":
                    raise RuntimeError(
                        f"视频生成失败: status={task['task_status']}, "
                        f"code={task['code']}, message={task['message']}"
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
        """封面优先复用本章首关键帧（显式传入），缺失时抽取视频首帧。

        不可直接使用链式首帧：那是上一章成片尾帧，会把封面误导为上一章画面。
        """
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

    # —— 串行链 ——

    async def start_chain(
        self,
        ctx,
        project_id: uuid.UUID,
        chapters: list[dict],
        *,
        use_images: bool = True,
        resolution: str | None = None,
        ratio: str | None = None,
        duration: int | None = None,
    ) -> dict:
        """按集顺序创建串行链：预建全部章节行，后台逐章执行并串接尾帧。"""
        if not ctx.user_id:
            bad_except("视频生成仅支持用户通道调用")
        if not use_images:
            bad_except("串行衔接需要关键帧图片，请开启「关键帧作参考图」")
        if not chapters:
            bad_except("请至少选择一个章节")
        if len(chapters) > MAX_CHAIN_CHAPTERS:
            bad_except(f"一次最多串行 {MAX_CHAIN_CHAPTERS} 个章节")

        existing = _chains.get(project_id.hex)
        if existing is not None and existing.running:
            bad_except("本项目已有串行生成任务在执行，请稍候")

        model_name = _video_model_name()
        ordered = sorted(
            chapters,
            key=lambda item: (
                item.get("chapter_no") is None,
                item.get("chapter_no") or 0,
            ),
        )
        seen_chapter_nos: set[int] = set()
        all_ids: list[uuid.UUID] = []
        for item in ordered:
            chapter_no = item.get("chapter_no")
            if chapter_no is not None:
                if chapter_no in seen_chapter_nos:
                    bad_except(f"第{chapter_no}集重复选择")
                seen_chapter_nos.add(chapter_no)
            ids = list(dict.fromkeys(item.get("keyframe_ids") or []))
            if not ids:
                bad_except(f"章节「{item.get('title') or '未命名'}」没有可用关键帧")
            item["keyframe_ids"] = ids
            all_ids.extend(ids)

        chain_id = uuid7().hex
        state = _ChainState(chain_id=chain_id, project_id=project_id, chapters=[])
        _chains[project_id.hex] = state
        try:
            keyframe_snapshots: dict[uuid.UUID, dict] = {}
            async with get_session() as session:
                await self._project_service._assert_owned(session, project_id, ctx)
                await self._assert_no_running_script(session, project_id)
                video_repo = VideoRepository(session)
                if await video_repo.has_active_for_project(project_id):
                    bad_except("本项目已有视频生成任务在执行，请稍候")

                unique_ids = list(dict.fromkeys(all_ids))
                by_id = await KeyframeRepository(session).get_many(unique_ids)
                if len(by_id) != len(unique_ids):
                    bad_except("部分关键帧不存在")
                for item in ordered:
                    title = item.get("title") or "未命名"
                    for keyframe_id in item["keyframe_ids"]:
                        keyframe = by_id.get(keyframe_id)
                        if keyframe is None or keyframe.project_id != project_id:
                            bad_except("部分关键帧不存在或不属于本项目")
                        if keyframe.status == StoryKeyframeStatus.ARCHIVED.value:
                            bad_except("存在已归档关键帧，无法生成视频")
                        if (
                            not keyframe.image_file
                            or not resolve_upload_path(keyframe.image_file).is_file()
                        ):
                            bad_except(f"章节「{title}」存在缺失图片的关键帧，请先出图")
                for keyframe_id, keyframe in by_id.items():
                    keyframe_snapshots[keyframe_id] = {
                        "id": keyframe.id,
                        "script_id": keyframe.script_id,
                        "image_file": keyframe.image_file,
                    }

            entries: list[_ChainEntry] = []
            total = len(ordered)
            prev_video_id: uuid.UUID | None = None
            for index, item in enumerate(ordered):
                chapter_no = item.get("chapter_no")
                title = (item.get("title") or "").strip() or (
                    f"第{chapter_no}集" if chapter_no is not None else "未匹配章节片段"
                )
                base_prompt = _truncate(
                    item.get("prompt") or "", VIDEO_PROMPT_MAX_CHARS
                )
                if not base_prompt:
                    bad_except(f"章节「{title}」的视频提示词为空")
                snapshots = [
                    keyframe_snapshots[keyframe_id]
                    for keyframe_id in item["keyframe_ids"]
                ]
                images = [
                    snapshot["image_file"]
                    for snapshot in snapshots
                    if snapshot["image_file"]
                ]
                video_id = uuid7()
                params = {
                    "chapter_no": chapter_no,
                    "chapter_title": title,
                    "chapter_content": _truncate(
                        item.get("chapter_content") or "",
                        CHAPTER_CONTENT_MAX,
                    )
                    or None,
                    "keyframe_ids": [snapshot["id"].hex for snapshot in snapshots],
                    "reference_images": images,
                    "use_images": True,
                    "first_frame_source": (
                        "own_first_keyframe" if index == 0 else "prev_tail"
                    ),
                    "first_frame_file": None,
                    "prev_video_id": (prev_video_id.hex if prev_video_id else None),
                    "link_degraded": False,
                    "resolution": resolution,
                    "ratio": ratio,
                    "duration": duration,
                    "chain_id": chain_id,
                    "chain_index": index,
                    "chain_total": total,
                }
                entries.append(
                    _ChainEntry(
                        video_id=video_id,
                        keyframe_id=snapshots[0]["id"],
                        script_id=snapshots[0]["script_id"],
                        base_prompt=base_prompt,
                        chapter_no=chapter_no,
                        title=title,
                        params=params,
                        reference_images=images,
                        cover_image_file=images[0] if images else None,
                        first_keyframe_image=images[0] if images else None,
                    )
                )
                prev_video_id = video_id

            created: list[dict] = []
            async with _project_task_lock(project_id.hex):
                async with get_session() as session:
                    video_repo = VideoRepository(session)
                    # 锁内复检：单章任务可能在本链校验与建行之间完成落库
                    if await video_repo.has_active_for_project(project_id):
                        bad_except("本项目已有视频生成任务在执行，请稍候")
                    for entry in entries:
                        await video_repo.create(
                            video_id=entry.video_id,
                            project_id=project_id,
                            keyframe_id=entry.keyframe_id,
                            script_id=entry.script_id,
                            source="generated",
                            title=entry.title,
                            episode_no=(
                                entry.chapter_no if entry.chapter_no is not None else 0
                            ),
                            status="queued",
                            provider="video",
                            model=model_name,
                            prompt=entry.base_prompt,
                            generation_params=entry.params,
                            target_platform="AI 生成",
                        )
                        created.append(
                            {
                                "video_id": entry.video_id.hex,
                                "chapter_no": entry.chapter_no,
                                "title": entry.title,
                            }
                        )
                    project = await ProjectRepository(session).get(project_id)
                    await ProjectRepository(session).recount_assets(project)
                    await session.commit()

            state.chapters = created
            try:
                state.task = asyncio.create_task(self._run_chain(state, entries))
                state.starting = False
                state.task.add_done_callback(
                    lambda done, st=state, ents=entries: self._handle_chain_done(
                        done, st, ents
                    )
                )
            except BaseException:
                # 任务未能启动时把已提交的 queued 行收尾，避免孤儿队列
                await self._cancel_remaining(entries, "串行链启动失败")
                raise
        except BaseException:
            if _chains.get(project_id.hex) is state:
                _chains.pop(project_id.hex, None)
            raise

        logger.info(
            f"[STORY] 串行链已创建 project={project_id.hex} chain={chain_id} "
            f"chapters={len(entries)}"
        )
        return {
            "chain_id": chain_id,
            "total": len(entries),
            "chapters": created,
        }

    async def _run_chain(self, state: _ChainState, entries: list[_ChainEntry]) -> None:
        """逐章串行执行：上一章成片尾帧作为下一章首帧。"""
        current_video_hex: str | None = None
        prev_snapshot: dict | None = None
        try:
            state.starting = False
            for index, entry in enumerate(entries):
                if state.cancel_requested:
                    raise asyncio.CancelledError
                state.cursor = index
                snapshot = await self._video_snapshot(entry.video_id)
                if snapshot is None or snapshot["status"] == "cancelled":
                    await self._cancel_remaining(entries[index:], "串行链已终止")
                    break

                if index == 0:
                    first_frame_file = entry.first_keyframe_image
                    first_frame_source = "own_first_keyframe"
                    link_degraded = False
                else:
                    first_frame_file = None
                    first_frame_source = "prev_tail"
                    link_degraded = False
                    if prev_snapshot is not None:
                        first_frame_file = await self._ensure_tail_frame(prev_snapshot)
                    if first_frame_file is None:
                        first_frame_file = entry.first_keyframe_image
                        first_frame_source = "own_first_keyframe"
                        link_degraded = True
                        logger.warning(
                            f"[STORY] 上一章尾帧不可用，降级用本章首关键帧 "
                            f"video={entry.video_id.hex}"
                        )

                prompt = (
                    _with_chain_note(entry.base_prompt)
                    if first_frame_source == "prev_tail"
                    else entry.base_prompt
                )
                await self._merge_params(
                    entry.video_id,
                    {
                        "first_frame_source": first_frame_source,
                        "first_frame_file": first_frame_file,
                        "link_degraded": link_degraded,
                    },
                )
                await self._update_video(entry.video_id, {"prompt": prompt})

                current_video_hex = entry.video_id.hex
                _video_tasks[current_video_hex] = asyncio.current_task()
                ok = await self._execute_video(
                    video_id=entry.video_id,
                    project_id=state.project_id,
                    keyframe_id=entry.keyframe_id,
                    prompt=prompt,
                    negative_prompt=None,
                    params=entry.params,
                    first_frame_file=first_frame_file,
                    reference_image_files=entry.reference_images,
                    cover_image_file=entry.cover_image_file,
                    send_references=True,
                    chain_mode=True,
                    prefer_first_frame=first_frame_source == "prev_tail",
                )
                _video_tasks.pop(current_video_hex, None)
                current_video_hex = None
                if not ok:
                    await self._cancel_remaining(
                        entries[index + 1 :],
                        "前序章节生成失败，串行链已终止",
                    )
                    break
                prev_snapshot = await self._video_snapshot(entry.video_id)
                state.cursor = index + 1
        except asyncio.CancelledError:
            await self._cancel_remaining(entries[state.cursor :], "串行链已中止")
            logger.warning(
                f"[STORY] 串行链被中止 project={state.project_id.hex} "
                f"chain={state.chain_id}"
            )
            raise
        except Exception as exc:
            # 后台链不允许漏出未处理异常；收尾剩余章节后正常结束
            logger.error(
                f"[STORY] 串行链异常终止 project={state.project_id.hex} "
                f"chain={state.chain_id}: {exc}"
            )
            try:
                await self._cancel_remaining(entries[state.cursor :], "串行链异常终止")
            except Exception as cancel_exc:
                logger.error(f"[STORY] 串行链收尾失败: {cancel_exc}")
        finally:
            if current_video_hex:
                _video_tasks.pop(current_video_hex, None)
            state.starting = False
            state.task = None
            logger.info(
                f"[STORY] 串行链结束 project={state.project_id.hex} "
                f"chain={state.chain_id}"
            )

    def _handle_chain_done(
        self,
        task: asyncio.Task,
        state: _ChainState,
        entries: list[_ChainEntry],
    ) -> None:
        """协程未启动即被取消时 finally 不会执行，这里补一次剩余章节收尾。"""
        if task.cancelled():
            try:
                asyncio.get_running_loop().create_task(
                    self._cancel_remaining(entries, "串行链已中止")
                )
            except RuntimeError:
                pass
        if _chains.get(state.project_id.hex) is state:
            state.starting = False
            if state.task is task:
                state.task = None

    async def _cancel_remaining(self, entries: list[_ChainEntry], message: str) -> None:
        """批量把链内剩余在途章节置为 cancelled。"""
        ids = [entry.video_id for entry in entries]
        if not ids:
            return
        async with get_session() as session:
            await VideoRepository(session).cancel_running(ids, message)
            await session.commit()

    async def chain_status(self, ctx, project_id: uuid.UUID) -> dict:
        """串行链实时状态：章节状态以数据库为准，前后端轮询共用。"""
        if not ctx.user_id:
            bad_except("视频操作仅支持用户通道调用")
        async with get_session() as session:
            await self._project_service._assert_owned(session, project_id, ctx)
            state = _chains.get(project_id.hex)
            if state is None:
                return {"running": False, "total": 0, "chapters": []}
            status_map: dict[str, str] = {}
            ids = [uuid.UUID(chapter["video_id"]) for chapter in state.chapters]
            if ids:
                rows = await session.execute(
                    select(StoryVideo.id, StoryVideo.status).where(
                        StoryVideo.id.in_(ids)
                    )
                )
                status_map = {row[0].hex: row[1] for row in rows.all()}

        chapters = [
            {**chapter, "status": status_map.get(chapter["video_id"], "unknown")}
            for chapter in state.chapters
        ]
        terminal = {"done", "failed", "cancelled"}
        finished = sum(1 for item in chapters if item["status"] in terminal)
        current = next(
            (item for item in chapters if item["status"] == "generating"),
            None,
        )
        if current is None:
            current = next(
                (item for item in chapters if item["status"] == "queued"),
                None,
            )
        current_chapter_no = (
            current["chapter_no"] if state.running and current else None
        )
        return {
            "running": state.running,
            "chain_id": state.chain_id,
            "total": len(chapters),
            "finished": finished,
            "success": sum(1 for item in chapters if item["status"] == "done"),
            "failed": sum(1 for item in chapters if item["status"] == "failed"),
            "cancelled": sum(1 for item in chapters if item["status"] == "cancelled"),
            "cursor": state.cursor,
            "current_chapter_no": current_chapter_no,
            "chapters": chapters,
        }

    async def stop(self, ctx, video_id: uuid.UUID) -> bool:
        """中止在途生成/合成任务（内存任务取消 + 上游 cancel + 状态终态化）。

        视频属于串行链时，停止当前章即终止整链（后续衔接已失去可靠首帧）。
        """
        if not ctx.user_id:
            bad_except("视频操作仅支持用户通道调用")
        cancelled = False
        remote_task_id: str | None = None
        chain_id: str | None = None
        async with get_session() as session:
            video = await self._assert_video_owned(session, video_id, ctx)
            params = video.generation_params or {}
            if isinstance(params, dict):
                chain_id = params.get("chain_id")
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
        if cancelled and chain_id:
            cancel_chain_for_video(video_id)
        return cancelled

    async def stop_all(self, ctx, project_id: uuid.UUID) -> int:
        """中止项目下全部在途视频生成/合成任务（含串行链）。"""
        if not ctx.user_id:
            bad_except("视频操作仅支持用户通道调用")
        stopped = 0
        remote_task_ids: list[str] = []
        async with get_session() as session:
            await self._project_service._assert_owned(session, project_id, ctx)
            # 属主校验通过后再取消内存链，避免越权取消他人项目
            cancel_chain(project_id.hex)
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
