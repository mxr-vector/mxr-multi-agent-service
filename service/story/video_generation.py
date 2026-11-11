"""
剧本模块视频片段生成业务层：按章节编排结果一次生成一个章节视频片段。

- 生成输入由编排层（service/story/video_plan.py）预填：章节正文 + 本镜头
  文本 + 关键帧提示词 + 出场角色；用户在面板中编辑确认后提交；
- 关键帧本地图片压缩后转 base64 data URI 作为参考图/首帧（DashScope 原生
  协议 wan3.0 走 media、旧模型走 img_url；聚合网关协议走 content 数组的
  first_frame / reference_image 角色），前端只提交必要字段，避免图片与
  长文本在浏览器往返；
- 任务生命周期：queued → generating → done / failed / cancelled。后台协程
  异步轮询上游任务（等待期间可取消），完成后立即下载落盘，封面优先复用
  关键帧图片，失败再抽视频首帧；
- 项目级并发上限 MAX_CONCURRENT_VIDEO_TASKS，超出任务保持 queued 等信号量；
- 只产出可下载的单镜头片段，整片由用户自行下载后外部组装。
"""

import asyncio
import shutil
import uuid
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
    VIDEO_EXTENSIONS,
    VIDEO_SUBDIR,
    extract_first_frame,
    probe_video_meta,
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

# 运行期任务注册表：video_id_hex -> asyncio.Task；项目信号量按需创建
_video_tasks: dict[str, asyncio.Task] = {}
_project_semaphores: dict[str, asyncio.Semaphore] = {}


def _project_semaphore(project_hex: str) -> asyncio.Semaphore:
    """获取项目级视频生成信号量（懒创建，同一事件循环内复用）。"""
    semaphore = _project_semaphores.get(project_hex)
    if semaphore is None:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_VIDEO_TASKS)
        _project_semaphores[project_hex] = semaphore
    return semaphore


def cancel_video_task(video_id: uuid.UUID) -> bool:
    """取消内存中的在途生成/合成任务（删除登记前调用，避免继续消耗上游额度）。"""
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
        logger.warning(f"[STORY] 上游任务取消超时（{REMOTE_CANCEL_TIMEOUT}s）: {task_id}")
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
    """仅在上游明确拒绝入参（400/413/422）时回退文生视频。

    鉴权失败、端点不存在、网络错误等与参考图无关，回退只会掩盖真实故障。
    """
    status = getattr(exc, "status_code", None)
    return status in (400, 413, 422)


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
    """视频片段生成业务层：项目属主校验收口，生成/轮询/下载。"""

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
        """为一个章节创建一个视频片段任务：一次提交该章全部关键帧参考图。

        提示词已由编排层把关键帧按剧本位置嵌入，前端确认后可编辑；服务端
        只负责校验、落库、提交一次模型任务，不再逐关键帧拆分。
        """
        if not ctx.user_id:
            bad_except("视频生成仅支持用户通道调用")
        final_prompt = _truncate(prompt or "", VIDEO_PROMPT_MAX_CHARS)
        if not final_prompt:
            bad_except("视频提示词不能为空")
        model_name = _video_model_name()

        ordered_ids = list(dict.fromkeys(keyframe_ids))
        if not ordered_ids:
            bad_except("本章没有可用的关键帧")
        episode_no = chapter_no if chapter_no is not None else 0

        async with get_session() as session:
            project = await self._project_service._assert_owned(
                session, project_id, ctx
            )
            running_script_stmt = (
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
            if await session.scalar(running_script_stmt) is not None:
                bad_except("本项目剧本生成进行中，请稍候")

            by_id = await KeyframeRepository(session).get_many(ordered_ids)
            if len(by_id) != len(ordered_ids):
                bad_except("部分关键帧不存在")
            keyframes = [by_id[keyframe_id] for keyframe_id in ordered_ids]
            if any(
                keyframe.project_id != project_id for keyframe in keyframes
            ):
                bad_except("部分关键帧不存在或不属于本项目")
            if any(
                keyframe.status == StoryKeyframeStatus.ARCHIVED.value
                for keyframe in keyframes
            ):
                bad_except("存在已归档关键帧，无法生成视频")

            video_repo = VideoRepository(session)
            if await video_repo.has_active_for_episode(project_id, episode_no):
                bad_except("本章片段正在生成中，请稍候")

            reference_images: list[str] = []
            if use_images:
                for keyframe in keyframes:
                    image_file = keyframe.image_file
                    if not image_file or not resolve_upload_path(image_file).is_file():
                        bad_except(
                            f"关键帧「{keyframe.name or keyframe.id.hex}」图片缺失，"
                            "请先在「关键帧」面板出图后再生成"
                        )
                    # 保留与图1…图N一一对应的顺序（重复图也不去重）
                    reference_images.append(image_file)

            final_title = (title or "").strip() or (
                f"第{chapter_no}集" if chapter_no is not None else "未匹配章节片段"
            )
            params = {
                "chapter_no": chapter_no,
                "chapter_title": final_title,
                "chapter_content": _truncate(
                    chapter_content or "", CHAPTER_CONTENT_MAX
                )
                or None,
                "keyframe_ids": [keyframe.id.hex for keyframe in keyframes],
                "reference_images": reference_images,
                "use_images": bool(reference_images),
                "resolution": resolution,
                "ratio": ratio,
                "duration": duration,
            }
            video = await video_repo.create(
                video_id=uuid7(),
                project_id=project_id,
                keyframe_id=keyframes[0].id,
                script_id=keyframes[0].script_id,
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
            await ProjectRepository(session).recount_assets(project)
            await session.commit()
            data = video.to_dict()
            video_id = video.id
            primary_keyframe_id = keyframes[0].id
            negative_prompt = None
            first_frame_file = reference_images[0] if len(reference_images) == 1 else None
            reference_image_files = (
                reference_images if len(reference_images) > 1 else []
            )

        task = asyncio.create_task(
            self._run_generation(
                video_id=video_id,
                project_id=project_id,
                keyframe_id=primary_keyframe_id,
                prompt=final_prompt,
                negative_prompt=negative_prompt,
                params=params,
                first_frame_file=first_frame_file,
                reference_image_files=reference_image_files,
            )
        )
        _video_tasks[video_id.hex] = task
        task.add_done_callback(
            lambda done, vid=video_id.hex: _video_tasks.pop(vid, None)
            if _video_tasks.get(vid) is done
            else None
        )
        logger.info(
            f"[STORY] 章节视频任务已创建 project={project_id.hex} "
            f"chapter={chapter_no} keyframes={len(keyframes)} "
            f"references={len(reference_images)}"
        )
        return data

    async def _update_video(self, video_id: uuid.UUID, fields: dict) -> None:
        """短会话更新视频状态；视频已被删除时静默忽略。"""
        async with get_session() as session:
            video = await VideoRepository(session).get(video_id)
            if video is None:
                return
            await VideoRepository(session).update_fields(video, fields)
            await session.commit()

    async def _run_generation(
        self,
        video_id: uuid.UUID,
        project_id: uuid.UUID,
        keyframe_id: uuid.UUID,
        prompt: str,
        negative_prompt: str | None,
        params: dict,
        first_frame_file: str | None,
        reference_image_files: list[str] | None = None,
    ) -> None:
        """后台生成协程：排队 → 提交（多参考图）→ 轮询 → 下载 → 封面 → 终态落库。"""
        semaphore = _project_semaphore(project_id.hex)
        video_rel: str | None = None
        effective_image_file = first_frame_file or (
            reference_image_files[0] if reference_image_files else None
        )
        task_id: str | None = None
        try:
            async with semaphore:
                await self._update_video(
                    video_id,
                    {"status": "generating", "error_message": None},
                )

                first_frame_url: str | None = None
                reference_urls: list[str] = []
                if params.get("use_images"):
                    if first_frame_file:
                        first_frame_url = await asyncio.to_thread(
                            image_to_reference_data_uri, first_frame_file
                        )
                    elif reference_image_files:
                        reference_urls = [
                            await asyncio.to_thread(image_to_reference_data_uri, file)
                            for file in reference_image_files
                        ]
                has_images = bool(first_frame_url or reference_urls)

                async def _submit(use_images: bool) -> str:
                    return await asyncio.to_thread(
                        submit_video,
                        prompt,
                        params.get("resolution"),
                        params.get("ratio"),
                        params.get("duration"),
                        first_frame_url=first_frame_url if use_images else None,
                        reference_image_urls=reference_urls if use_images else None,
                        negative_prompt=negative_prompt,
                    )

                try:
                    task_id = await _submit(True)
                except Exception as exc:
                    if not has_images or not _image_fallback_allowed(exc):
                        raise
                    # 模型不支持首帧/多参考图时回退文生视频一次，避免整章失败
                    logger.warning(
                        f"[STORY] 参考图视频提交失败，回退文生视频 video={video_id.hex}: {exc}"
                    )
                    task_id = await _submit(False)
                    effective_image_file = None
                    await self._update_video(
                        video_id,
                        {
                            "generation_params": {
                                **params,
                                "image_fallback": True,
                            }
                        },
                    )

                await self._update_video(video_id, {"external_task_id": task_id})
                task = await self._wait_task(task_id)
                if task["task_status"] != "SUCCEEDED" and has_images:
                    # 上游可能在任务阶段拒绝参考图，回退文生视频重试一次
                    logger.warning(
                        f"[STORY] 参考图视频任务失败，回退文生视频重试 video={video_id.hex}: "
                        f"status={task['task_status']} code={task['code']} message={task['message']}"
                    )
                    task_id = await _submit(False)
                    effective_image_file = None
                    await self._update_video(
                        video_id,
                        {
                            "external_task_id": task_id,
                            "generation_params": {
                                **params,
                                "image_fallback": True,
                            },
                        },
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
                    video_id, effective_image_file, video_rel
                )
                await self._update_video(
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
                logger.info(
                    f"[STORY] 视频生成完成 video={video_id.hex} "
                    f"keyframe={keyframe_id.hex} file={video_rel}"
                )
        except asyncio.CancelledError:
            logger.warning(f"[STORY] 视频生成被取消 video={video_id.hex}")
            await _cancel_remote_task(task_id)
            await self._update_video(
                video_id,
                {"status": "cancelled", "error_message": "用户主动中止生成"},
            )
            if video_rel:
                await asyncio.to_thread(unlink_quietly, video_rel)
            raise
        except Exception as exc:
            logger.error(f"[STORY] 视频生成失败 video={video_id.hex}: {exc}")
            await self._update_video(
                video_id,
                {"status": "failed", "error_message": str(exc)[:500]},
            )
            if video_rel:
                await asyncio.to_thread(unlink_quietly, video_rel)
        finally:
            _video_tasks.pop(video_id.hex, None)

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
        first_frame_file: str | None,
        video_rel: str,
    ) -> str | None:
        """封面优先复用关键帧图片（与首帧一致），缺失时抽取视频首帧。"""
        if first_frame_file:
            target: Path | None = None
            try:
                source = resolve_upload_path(first_frame_file)
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
