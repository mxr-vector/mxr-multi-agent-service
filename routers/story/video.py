"""
剧本模块视频成品路由：上传登记（抽首帧封面）、列表与维护。

上传守卫对齐既有模式（格式白名单 + 大小上限），视频大小上限与图片分离
（VIDEO_UPLOAD_MAX_SIZE_MB）；封面默认服务端抽帧，失败降级手动上传。
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, Path, Query, UploadFile
from pydantic import BaseModel

from exception.bad_except import bad_except
from service.story.storage import IMAGE_EXTENSIONS
from service.story.video import (
    VIDEO_EXTENSIONS,
    VideoService,
)
from utils.env import ENV
from utils.page import build_page_result
from utils.response import R
from utils.user_context import UserContext, get_user_context

router = APIRouter(prefix="/story", tags=["OpenAPI - 剧本视频成品"])

_video_service = VideoService()


class VideoUpdateRequest(BaseModel):
    """编辑视频登记请求体：溯源字段不可改。"""

    title: Optional[str] = None
    episode_no: Optional[int] = None
    target_platform: Optional[str] = None
    external_task_id: Optional[str] = None
    remark: Optional[str] = None


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
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    ctx: UserContext = Depends(get_user_context),
):
    """项目视频列表（可选按关键帧过滤），创建时间倒序。"""
    items, total = await _video_service.list(ctx, project_id, keyframe_id, page, size)
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
    data = await file.read()
    max_bytes = ENV.upload_max_size_mb * 1024 * 1024
    if len(data) > max_bytes:
        bad_except(f"图片超过大小上限（{ENV.upload_max_size_mb}MB）")
    return R.success(data=await _video_service.upload_cover(ctx, video_id, data, ext))


@router.post("/videos/{video_id}/project-cover")
async def set_project_cover(
    video_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """把视频封面设为项目封面。"""
    return R.success(data=await _video_service.set_project_cover(ctx, video_id))
