"""
剧本模块视频路由：
1. 外部成品回收：上传登记（抽首帧封面）、列表与维护；
2. 章节化片段生成：读取剧本编排 → 用户确认整章提示词 → 一次生成/下载；
3. 关联集：对相邻两集已完成片段抽首尾帧，生成集间衔接片段。

上传守卫对齐既有模式（格式白名单 + 大小上限），视频大小上限与图片分离
（VIDEO_UPLOAD_MAX_SIZE_MB）；封面默认服务端抽帧，失败降级手动上传。
生成接口接收用户确认后的整章提示词与该章全部关键帧（参考图一次性提交）。
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, Path, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from exception.bad_except import bad_except
from service.story.storage import IMAGE_EXTENSIONS
from service.story.video import (
    VIDEO_EXTENSIONS,
    VideoService,
)
from service.story.video_generation import VideoGenerationService
from service.story.video_plan import VideoPlanService
from utils.env import ENV
from utils.page import build_page_result
from utils.response import R
from utils.user_context import UserContext, get_user_context
from utils.file_ingest import read_upload_capped

router = APIRouter(prefix="/story", tags=["OpenAPI - 剧本视频成品"])

_video_service = VideoService()
_video_generation_service = VideoGenerationService()
_video_plan_service = VideoPlanService()

_VIDEO_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
}


class VideoUpdateRequest(BaseModel):
    """编辑视频登记请求体：溯源字段不可改。"""

    title: Optional[str] = None
    episode_no: Optional[int] = None
    target_platform: Optional[str] = None
    external_task_id: Optional[str] = None
    remark: Optional[str] = None


class ChapterVideoGenerateRequest(BaseModel):
    """章节片段生成请求体：一章一份提示词 + 该章全部关键帧。"""

    chapter_no: Optional[int] = None
    title: Optional[str] = None
    prompt: str = Field(..., min_length=1)
    keyframe_ids: list[uuid.UUID] = Field(default_factory=list)
    chapter_content: Optional[str] = None
    use_images: bool = True
    resolution: Optional[str] = None
    ratio: Optional[str] = None
    duration: Optional[int] = Field(default=None, ge=2, le=30)


class VideoLinkCreateRequest(BaseModel):
    """集间衔接片段请求体：相邻两集的已完成片段 + 可编辑提示词/规格。"""

    from_video_id: uuid.UUID
    to_video_id: uuid.UUID
    prompt: Optional[str] = None
    resolution: Optional[str] = None
    ratio: Optional[str] = None
    duration: Optional[int] = Field(default=None, ge=2, le=30)


@router.get("/projects/{project_id}/video-plan")
async def project_video_plan(
    project_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """章节化编排：把该章剧本正文与全部关键帧按位置组合成一份生成单元。"""
    return R.success(data=await _video_plan_service.plan(ctx, project_id))


@router.post("/projects/{project_id}/videos/generate")
async def generate_project_video(
    project_id: uuid.UUID = Path(...),
    payload: ChapterVideoGenerateRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """生成一个章节片段：一次提交该章提示词与全部关键帧参考图。"""
    return R.success(
        data=await _video_generation_service.generate_chapter(
            ctx,
            project_id,
            prompt=payload.prompt,
            keyframe_ids=payload.keyframe_ids,
            title=payload.title,
            chapter_no=payload.chapter_no,
            chapter_content=payload.chapter_content,
            use_images=payload.use_images,
            resolution=payload.resolution,
            ratio=payload.ratio,
            duration=payload.duration,
        )
    )


@router.get("/projects/{project_id}/video-links")
async def project_video_links(
    project_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """关联集视图：每集最新已完成片段 + 相邻集衔接片段（供轮询）。"""
    return R.success(data=await _video_generation_service.list_links(ctx, project_id))


@router.post("/projects/{project_id}/video-links")
async def create_project_video_link(
    project_id: uuid.UUID = Path(...),
    payload: VideoLinkCreateRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """生成集间衔接片段：上一集成片尾帧作首帧、下一集成片首帧作尾帧。"""
    return R.success(
        data=await _video_generation_service.create_link(
            ctx,
            project_id,
            from_video_id=payload.from_video_id,
            to_video_id=payload.to_video_id,
            prompt=payload.prompt,
            resolution=payload.resolution,
            ratio=payload.ratio,
            duration=payload.duration,
        )
    )


@router.get("/videos/generation-options")
async def video_generation_options(
    ctx: UserContext = Depends(get_user_context),
):
    """生成面板公共配置：默认规格与并发上限（不含敏感凭证）。"""
    return R.success(data=_video_generation_service.generation_options())


@router.post("/videos/{video_id}/stop")
async def stop_video_generation(
    video_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """中止在途视频生成任务，状态置为 cancelled。"""
    cancelled = await _video_generation_service.stop(ctx, video_id)
    return R.success(data={"cancelled": cancelled})


@router.post("/projects/{project_id}/videos/stop-all")
async def stop_all_video_generations(
    project_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """中止本项目下全部在途视频生成任务。"""
    stopped_count = await _video_generation_service.stop_all(ctx, project_id)
    return R.success(data={"stopped_count": stopped_count})


@router.get("/videos/{video_id}/download")
async def download_video(
    video_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """下载单个视频片段（附件流式下发，文件名取片段标题）。"""
    path, filename = await _video_service.download(ctx, video_id)
    media_type = _VIDEO_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        headers={"Access-Control-Expose-Headers": "Content-Disposition"},
    )


@router.post("/projects/{project_id}/videos")
async def upload_video(
    project_id: uuid.UUID = Path(...),
    file: UploadFile = File(..., description="视频成品（mp4/mov/webm/mkv）"),
    title: Optional[str] = Form(default=None),
    episode_no: Optional[int] = Form(
        default=None, description="分组/排序号（语义宽松）"
    ),
    keyframe_id: Optional[uuid.UUID] = Form(
        default=None, description="主溯源：来源关键帧"
    ),
    script_id: Optional[uuid.UUID] = Form(default=None),
    export_package_id: Optional[uuid.UUID] = Form(default=None),
    target_platform: Optional[str] = Form(default=None, description="生成平台备注"),
    external_task_id: Optional[str] = Form(default=None),
    remark: Optional[str] = Form(default=None),
    ctx: UserContext = Depends(get_user_context),
):
    """上传视频片段并登记：扩展名白名单校验后交由业务层处理。

    业务层流程为「属主/溯源校验 → 分块流式落盘（强制大小上限）→
    元数据/首帧封面 → 入库」，校验不通过不落盘，入库失败自动清理文件；
    封面抽帧失败降级为无封面，可后续手动上传。
    """
    ext = (
        file.filename.rsplit(".", 1)[-1].lower()
        if file.filename and "." in file.filename
        else ""
    )
    if ext not in VIDEO_EXTENSIONS:
        bad_except(
            f"不支持的视频类型: {file.filename or '(无扩展名)'}"
            f"（仅 {'/'.join(sorted(VIDEO_EXTENSIONS))}）"
        )

    video = await _video_service.register(
        ctx,
        project_id,
        upload=file,
        ext=ext,
        keyframe_id=keyframe_id,
        script_id=script_id,
        export_package_id=export_package_id,
        title=title,
        episode_no=episode_no,
        target_platform=target_platform,
        external_task_id=external_task_id,
        remark=remark,
    )
    return R.success(data=video)


@router.get("/projects/{project_id}/videos")
async def list_videos(
    project_id: uuid.UUID = Path(...),
    keyframe_id: Optional[uuid.UUID] = Query(
        default=None, description="按关键帧过滤（关键帧反查片段）"
    ),
    source: Optional[str] = Query(
        default=None, description="来源过滤：upload/generated"
    ),
    status: Optional[str] = Query(
        default=None, description="状态过滤：queued/generating/done/failed/cancelled"
    ),
    brief: bool = Query(
        default=False, description="精简模式：省略提示词/生成参数等大字段"
    ),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    ctx: UserContext = Depends(get_user_context),
):
    """项目视频列表（可选按关键帧/来源/状态过滤），创建时间倒序。"""
    items, total = await _video_service.list(
        ctx, project_id, keyframe_id, page, size, source, status, brief
    )
    return R.success(data=build_page_result(items, total, page, size))


@router.put("/videos/{video_id}")
async def update_video(
    video_id: uuid.UUID = Path(...),
    payload: VideoUpdateRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """编辑视频登记字段（溯源字段不可改）。"""
    return R.success(data=await _video_service.update(ctx, video_id, payload))


@router.delete("/videos/{video_id}")
async def delete_video(
    video_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """删除视频登记（不级联溯源对象）。"""
    await _video_service.delete(ctx, video_id)
    return R.success()


@router.post("/videos/{video_id}/cover")
async def upload_video_cover(
    video_id: uuid.UUID = Path(...),
    file: UploadFile = File(..., description="封面图片（png/jpg/jpeg/webp）"),
    ctx: UserContext = Depends(get_user_context),
):
    """手动上传视频封面（抽帧降级路径或自定义封面）。

    业务层流程为「校验视频归属 → 落盘 → 更新封面 → 失败清理」，
    校验不通过（如传入他人 video_id）不落盘，杜绝孤儿文件。
    """
    ext = (
        file.filename.rsplit(".", 1)[-1].lower()
        if file.filename and "." in file.filename
        else ""
    )
    if ext not in IMAGE_EXTENSIONS:
        bad_except(
            f"不支持的图片类型: {file.filename or '(无扩展名)'}（仅 png/jpg/jpeg/webp）"
        )
    # 分块读取并即时校验（Content-Length 可伪造），超限在载入全量内存前即拒绝
    data = await read_upload_capped(file, ENV.upload_max_size_mb * 1024 * 1024)
    return R.success(data=await _video_service.upload_cover(ctx, video_id, data, ext))


@router.post("/videos/{video_id}/project-cover")
async def set_project_cover(
    video_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """把视频封面设为项目封面。"""
    return R.success(data=await _video_service.set_project_cover(ctx, video_id))
