"""
剧本模块视频成品业务层：上传登记、首帧封面与维护。

- 上传流程为「校验前置 → 流式落盘 → 转码探测 → 入库」：属主/溯源校验
  通过前不写盘；分块流式写入并强制大小上限（不做整文件内存缓冲）；
  ffprobe/ffmpeg 在数据库会话之外执行，避免长事务钉住连接池；
  入库失败回滚清理已写文件，不留孤儿；
- 抽帧失败或 ffmpeg 缺失时不阻断登记，封面留空（降级路径，允许手动上传）；
- 时长/宽高等元数据经 ffprobe 尽力解析，失败不阻断；
- 溯源字段（关键帧/剧本/导出包）须与视频同属一个项目；
- 删除不级联溯源对象，视频文件不追删（对齐 draw 的文件处理约定）。
"""

import asyncio
import json
import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import UploadFile
from uuid_utils.compat import uuid7

from database.postgre_client import get_session
from database.story.project import (
    ExportPackageRepository,
    KeyframeRepository,
    ProjectRepository,
    ScriptRepository,
)
from database.story.video import VideoRepository
from exception.bad_except import bad_except
from service.story.project import ProjectService
from service.story.storage import (
    assert_asset_relative,
    resolve_upload_path,
    sanitize_dir_name,
    unlink_quietly,
)
from utils.env import ENV
from utils.logger import logger

# 视频上传扩展名白名单
VIDEO_EXTENSIONS = {"mp4", "mov", "webm", "mkv"}

# 上传子目录
VIDEO_SUBDIR = "story/video"
COVER_SUBDIR = "story/video-cover"
# 手动上传封面子目录（抽帧降级路径或自定义封面）
COVER_UPLOAD_SUBDIR = "story/video-cover-upload"
# 串行衔接尾帧子目录（上一章成片最后一帧，作为下一章首帧）
FRAME_SUBDIR = "story/video-frame"

# 视频大小上限（MB）：与图片上传上限分离，经 ENV property require() fail-loudly
VIDEO_MAX_SIZE_MB = ENV.video_upload_max_size_mb

# ffmpeg 探测（模块加载即启动探测，缺失则全局降级为手动封面）
_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")
if _FFMPEG is None:
    logger.warning("[STORY] 未检测到 ffmpeg，视频封面将降级为手动上传")

# 视频可更新字段白名单（溯源字段登记后不可改，防脏引用）
_VIDEO_UPDATABLE = {
    "title",
    "episode_no",
    "target_platform",
    "external_task_id",
    "remark",
}


def probe_video_meta(path: Path) -> dict:
    """ffprobe 尽力解析 duration_ms/width/height，失败返回空字典（不抛异常）。"""
    if _FFPROBE is None:
        return {}
    try:
        result = subprocess.run(
            [
                _FFPROBE,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return {}
        info = json.loads(result.stdout or "{}")
        meta: dict = {}
        duration = (info.get("format") or {}).get("duration")
        if duration:
            meta["duration_ms"] = int(float(duration) * 1000)
        for stream in info.get("streams") or []:
            if stream.get("codec_type") == "video":
                if stream.get("width"):
                    meta["width"] = int(stream["width"])
                if stream.get("height"):
                    meta["height"] = int(stream["height"])
                break
        return meta
    except Exception as exc:  # 元数据缺失不阻断登记
        logger.warning(f"[STORY] 视频元数据解析失败: {exc}")
        return {}


def extract_first_frame(video_path: Path, cover_path: Path) -> bool:
    """抽取视频第一帧为封面（同步执行，60 秒超时），返回是否成功。"""
    if _FFMPEG is None:
        return False
    try:
        result = subprocess.run(
            [
                _FFMPEG,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(cover_path),
            ],
            capture_output=True,
            timeout=60,
        )
        return (
            result.returncode == 0
            and cover_path.is_file()
            and cover_path.stat().st_size > 0
        )
    except Exception as exc:  # 抽帧失败降级为无封面
        logger.warning(f"[STORY] 视频首帧抽取失败: {exc}")
        return False


def extract_last_frame(video_path: Path, frame_path: Path) -> bool:
    """抽取视频最后一帧（同步执行，60 秒超时），返回是否成功。

    串行衔接用：先按末尾 0.1s 定位，失败再回退末尾 1s。写入临时文件后
    原子替换，重复抽取幂等；任何失败只告警返回 False，由调用方降级。
    """
    if _FFMPEG is None:
        return False
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    # 唯一临时名：多章并发补抽同一前序尾帧时互不覆盖
    temp_path = frame_path.with_name(
        f"{frame_path.stem}.{uuid.uuid4().hex}.tmp.jpg"
    )
    for seek in ("-0.1", "-1"):
        try:
            result = subprocess.run(
                [
                    _FFMPEG,
                    "-y",
                    "-loglevel",
                    "error",
                    "-sseof",
                    seek,
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    "-update",
                    "1",
                    "-q:v",
                    "2",
                    str(temp_path),
                ],
                capture_output=True,
                timeout=60,
            )
            if (
                result.returncode == 0
                and temp_path.is_file()
                and temp_path.stat().st_size > 0
            ):
                temp_path.replace(frame_path)
                return True
        except Exception as exc:
            logger.warning(f"[STORY] 视频尾帧抽取失败(seek={seek}): {exc}")
        finally:
            temp_path.unlink(missing_ok=True)
    logger.warning(f"[STORY] 视频尾帧抽取最终失败: {video_path}")
    return False


class VideoService:
    """视频成品业务层：项目属主校验收口。"""

    def __init__(self) -> None:
        self._project_service = ProjectService()

    async def _assert_video_owned(self, session, video_id: uuid.UUID, ctx):
        """视频须存在且所属项目归当前用户。"""
        video = await VideoRepository(session).get(video_id)
        if video is None:
            bad_except("视频不存在")
        await self._project_service._assert_owned(session, video.project_id, ctx)
        return video

    async def register(
        self,
        ctx,
        project_id: uuid.UUID,
        upload: UploadFile,
        ext: str,
        *,
        keyframe_id: uuid.UUID | None = None,
        script_id: uuid.UUID | None = None,
        export_package_id: uuid.UUID | None = None,
        title: str | None = None,
        episode_no: int | None = None,
        target_platform: str | None = None,
        external_task_id: str | None = None,
        remark: str | None = None,
    ) -> dict:
        """登记视频片段：校验前置 → 流式落盘 → 元数据/首帧（不占会话）→ 入库。

        入库失败时回滚清理已写入的视频与封面文件，不留孤儿。
        """
        if target_platform and len(target_platform) > 100:
            bad_except("平台备注不能超过 100 字符")
        if external_task_id and len(external_task_id) > 200:
            bad_except("外部任务号不能超过 200 字符")

        # 1) 校验（短会话）：属主与溯源必须先行，未通过不落盘
        async with get_session() as session:
            await self._project_service._assert_owned(session, project_id, ctx)
            if keyframe_id is not None:
                keyframe = await KeyframeRepository(session).get(keyframe_id)
                if keyframe is None or keyframe.project_id != project_id:
                    bad_except("溯源关键帧不存在或不属于本项目")
            if script_id is not None:
                script = await ScriptRepository(session).get(script_id)
                if script is None or script.project_id != project_id:
                    bad_except("溯源剧本不存在或不属于本项目")
            if export_package_id is not None:
                package = await ExportPackageRepository(session).get(export_package_id)
                if package is None or package.project_id != project_id:
                    bad_except("溯源导出包不存在或不属于本项目")

        # 2) 流式落盘（逐块写入并强制大小上限，不做整文件内存缓冲）
        relative = f"{VIDEO_SUBDIR}/{uuid7().hex}.{ext}"
        video_path = ENV.upload_dir / relative
        file_size = await self._stream_save(upload, video_path)

        # 3) 元数据 + 首帧封面（无会话占用，避免长事务钉住连接池）
        cover_rel = f"{COVER_SUBDIR}/{uuid7().hex}.jpg"
        cover_path = ENV.upload_dir / cover_rel

        def _probe_and_extract() -> tuple[dict, bool]:
            cover_path.parent.mkdir(parents=True, exist_ok=True)
            meta = probe_video_meta(video_path)
            ok = extract_first_frame(video_path, cover_path)
            return meta, ok

        meta, cover_ok = await asyncio.to_thread(_probe_and_extract)
        if not cover_ok:
            cover_rel = None
            logger.info(f"[STORY] 视频封面未生成（降级手动上传）: {relative}")

        # 4) 入库（短会话）；失败回滚清理已写文件
        try:
            async with get_session() as session:
                video = await VideoRepository(session).create(
                    video_id=uuid7(),
                    project_id=project_id,
                    video_file=relative,
                    keyframe_id=keyframe_id,
                    script_id=script_id,
                    export_package_id=export_package_id,
                    title=title,
                    episode_no=episode_no,
                    cover_file=cover_rel,
                    file_size=file_size,
                    target_platform=target_platform,
                    external_task_id=external_task_id,
                    remark=remark,
                    **meta,
                )
                project = await ProjectRepository(session).get(project_id)
                await ProjectRepository(session).recount_assets(project)
                await session.commit()
                return video.to_dict()
        except Exception:

            def _rollback() -> None:
                video_path.unlink(missing_ok=True)
                cover_path.unlink(missing_ok=True)

            await asyncio.to_thread(_rollback)
            raise

    async def _stream_save(self, upload: UploadFile, target: Path) -> int:
        """分块流式写入目标文件并强制大小上限；超限/失败时清理半成品。

        返回实际写入字节数。须在 asyncio.to_thread 中执行（同步文件 IO）。
        """
        max_bytes = VIDEO_MAX_SIZE_MB * 1024 * 1024

        def _write() -> int:
            target.parent.mkdir(parents=True, exist_ok=True)
            total = 0
            try:
                with open(target, "wb") as handle:
                    while True:
                        chunk = upload.file.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            bad_except(f"视频超过大小上限（{VIDEO_MAX_SIZE_MB}MB）")
                        handle.write(chunk)
            except Exception:
                target.unlink(missing_ok=True)
                raise
            return total

        return await asyncio.to_thread(_write)

    async def list(
        self,
        ctx,
        project_id: uuid.UUID,
        keyframe_id: uuid.UUID | None = None,
        page: int = 1,
        size: int = 20,
        source: str | None = None,
        status: str | None = None,
        brief: bool = False,
    ):
        """项目视频列表（可按关键帧/来源/状态过滤），创建时间倒序。

        brief=True 时剔除长提示词/生成参数，供前端轮询时降低传输量。
        """
        async with get_session() as session:
            await self._project_service._assert_owned(session, project_id, ctx)
            items, total = await VideoRepository(session).list(
                project_id, keyframe_id, page, size, source, status
            )
            result = [item.to_dict() for item in items]
            if brief:
                for item in result:
                    item.pop("prompt", None)
                    item.pop("negative_prompt", None)
                    item.pop("generation_params", None)
            return result, total

    async def update(self, ctx, video_id: uuid.UUID, payload) -> dict:
        """编辑视频登记字段（白名单内显式传入；溯源字段不可改）。"""
        async with get_session() as session:
            video = await self._assert_video_owned(session, video_id, ctx)
            fields = {
                key: value
                for key, value in payload.model_dump(exclude_unset=True).items()
                if key in _VIDEO_UPDATABLE
            }
            if not fields:
                bad_except("没有可更新的字段")
            if fields.get("target_platform") and len(fields["target_platform"]) > 100:
                bad_except("平台备注不能超过 100 字符")
            if fields.get("external_task_id") and len(fields["external_task_id"]) > 200:
                bad_except("外部任务号不能超过 200 字符")
            await VideoRepository(session).update_fields(video, fields)
            await session.commit()
            return video.to_dict()

    async def delete(self, ctx, video_id: uuid.UUID) -> None:
        """删除视频登记（不级联溯源对象），重算项目计数。

        仅对模型生成/合成的本地文件做精确清理；外部上传文件沿用既有
        「不追删」约定，避免误删用户手工归档的原始素材。
        """
        async with get_session() as session:
            video = await self._assert_video_owned(session, video_id, ctx)
            project_id = video.project_id
            source = video.source
            video_file = video.video_file
            cover_file = video.cover_file
            params = video.generation_params or {}
            tail_frame_file = (
                params.get("tail_frame_file") if isinstance(params, dict) else None
            )
            chain_id = params.get("chain_id") if isinstance(params, dict) else None
            if source == "generated":
                # 在途任务先取消；链内任意章节被删都会破坏后续衔接，整链终止
                from service.story.video_generation import (
                    cancel_chain_for_video,
                    cancel_video_task,
                )

                cancel_video_task(video.id)
                if chain_id:
                    cancel_chain_for_video(video.id)
            await VideoRepository(session).delete(video)
            project_repo = ProjectRepository(session)
            project = await project_repo.get(project_id)
            await project_repo.recount_assets(project)
            await session.commit()

        if source == "generated":
            def _cleanup() -> None:
                if video_file:
                    unlink_quietly(video_file)
                if cover_file:
                    unlink_quietly(cover_file)
                if tail_frame_file:
                    unlink_quietly(tail_frame_file)

            await asyncio.to_thread(_cleanup)

    async def download(self, ctx, video_id: uuid.UUID) -> tuple[Path, str]:
        """校验归属并返回视频文件与下载文件名（供路由流式下发）。"""
        async with get_session() as session:
            video = await self._assert_video_owned(session, video_id, ctx)
            if not video.video_file:
                bad_except("视频尚未生成完成")
            path = resolve_upload_path(video.video_file)
            if not path.is_file():
                bad_except("视频文件不存在或已被清理")
            stem = sanitize_dir_name(video.title or "视频片段", video.id.hex)
            return path, f"{stem}{path.suffix}"

    async def set_cover(self, ctx, video_id: uuid.UUID, cover_file: str) -> dict:
        """手动设置封面（抽帧降级路径或自定义封面）。"""
        assert_asset_relative(cover_file, ("story/",))
        async with get_session() as session:
            video = await self._assert_video_owned(session, video_id, ctx)
            await VideoRepository(session).update_fields(
                video, {"cover_file": cover_file}
            )
            await session.commit()
            return video.to_dict()

    async def upload_cover(
        self, ctx, video_id: uuid.UUID, file_data: bytes, ext: str
    ) -> dict:
        """手动上传视频封面：校验前置 → 落盘 → 更新封面；入库失败回滚清理。

        对齐 register 的「属主校验 → 落盘 → 入库 → 失败回滚清理」，杜绝校验
        失败（如传入他人 video_id）时字节已写盘遗留孤儿文件。
        """
        # 1) 校验前置（短会话）：属主未通过不落盘
        async with get_session() as session:
            await self._assert_video_owned(session, video_id, ctx)
        # 2) 落盘
        relative = f"{COVER_UPLOAD_SUBDIR}/{uuid7().hex}.{ext}"
        cover_path = ENV.upload_dir / relative

        def _save() -> None:
            cover_path.parent.mkdir(parents=True, exist_ok=True)
            cover_path.write_bytes(file_data)

        await asyncio.to_thread(_save)
        # 3) 更新封面；失败回滚清理已写文件（不留孤儿）
        try:
            return await self.set_cover(ctx, video_id, relative)
        except Exception:
            await asyncio.to_thread(lambda: cover_path.unlink(missing_ok=True))
            raise

    async def set_project_cover(self, ctx, video_id: uuid.UUID) -> dict:
        """把视频封面设为项目封面（视频须已有封面）。"""
        async with get_session() as session:
            video = await self._assert_video_owned(session, video_id, ctx)
            if not video.cover_file:
                bad_except("该视频还没有封面，请先生成或上传封面")
            project_repo = ProjectRepository(session)
            project = await project_repo.get(video.project_id)
            await project_repo.update_fields(project, {"cover_image": video.cover_file})
            await session.commit()
            return project.to_dict()
