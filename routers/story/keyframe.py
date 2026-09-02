"""
剧本模块关键帧路由：五段式描述维护、出场角色登记。
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Path, Query, UploadFile
from pydantic import BaseModel

from exception.bad_except import bad_except
from service.story.keyframe import KeyframeService
from service.story.storage import IMAGE_EXTENSIONS
from utils.env import ENV
from utils.page import build_page_result
from utils.response import R
from utils.user_context import UserContext, get_user_context

router = APIRouter(prefix="/story", tags=["OpenAPI - 剧本关键帧"])

_keyframe_service = KeyframeService()


class KeyframeCharacterEntry(BaseModel):
    """关键帧出场角色条目。"""

    character_id: uuid.UUID
    character_art_id: Optional[uuid.UUID] = None
    role: Optional[str] = None  # 'main'/'secondary'/'background'
    character_prompt: Optional[str] = None


class KeyframeCreateRequest(BaseModel):
    """创建关键帧请求体：正向提示词必填，其余按需。"""

    prompt: str
    script_id: Optional[uuid.UUID] = None
    chapter_no: Optional[int] = None
    scene_no: Optional[int] = None
    shot_no: Optional[int] = None
    name: Optional[str] = None
    scene_description: Optional[str] = None
    visual_description: Optional[str] = None
    camera_description: Optional[str] = None
    lighting_description: Optional[str] = None
    style_description: Optional[str] = None
    negative_prompt: Optional[str] = None
    reference_images: list = []
    characters: list[KeyframeCharacterEntry] = []


class KeyframeUpdateRequest(BaseModel):
    """编辑关键帧请求体：仅显式传入的字段生效。

    图片字段不接受客户端直写（防路径穿越），图片经
    POST /story/keyframes/{id}/image 上传端点维护。
    """

    script_id: Optional[uuid.UUID] = None
    chapter_no: Optional[int] = None
    scene_no: Optional[int] = None
    shot_no: Optional[int] = None
    name: Optional[str] = None
    scene_description: Optional[str] = None
    visual_description: Optional[str] = None
    camera_description: Optional[str] = None
    lighting_description: Optional[str] = None
    style_description: Optional[str] = None
    prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    reference_images: Optional[list] = None
    status: Optional[str] = None


class KeyframeCharactersRequest(BaseModel):
    """整体设置出场角色请求体。"""

    characters: list[KeyframeCharacterEntry]


class KeyframeSelectionRequest(BaseModel):
    """关键帧选择请求体：按导出顺序给出关键帧 id（空列表清空）。"""

    keyframe_ids: list[uuid.UUID]


@router.get("/projects/{project_id}/keyframes")
async def list_keyframes(
    project_id: uuid.UUID = Path(...),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=100),
    ctx: UserContext = Depends(get_user_context),
):
    """项目关键帧列表（含出场角色摘要），按编号升序。"""
    items, total = await _keyframe_service.list(ctx, project_id, page, size)
    return R.success(data=build_page_result(items, total, page, size))


@router.put("/projects/{project_id}/keyframe-selection")
async def set_keyframe_selection(
    project_id: uuid.UUID = Path(...),
    payload: KeyframeSelectionRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """整体设置导出选中关键帧；关键帧须归属本项目。"""
    return R.success(
        data=await _keyframe_service.set_selection(
            ctx, project_id, payload.keyframe_ids
        )
    )


@router.post("/projects/{project_id}/keyframes")
async def create_keyframe(
    project_id: uuid.UUID = Path(...),
    payload: KeyframeCreateRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """创建关键帧：（场景号, 镜头号）冲突校验 + 出场角色登记。"""
    return R.success(data=await _keyframe_service.create(ctx, project_id, payload))


@router.get("/keyframes/{keyframe_id}")
async def keyframe_detail(
    keyframe_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """关键帧详情（含出场角色）。"""
    return R.success(data=await _keyframe_service.detail(ctx, keyframe_id))


@router.put("/keyframes/{keyframe_id}")
async def update_keyframe(
    keyframe_id: uuid.UUID = Path(...),
    payload: KeyframeUpdateRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """编辑关键帧：编号变更时重新校验冲突。"""
    return R.success(data=await _keyframe_service.update(ctx, keyframe_id, payload))


@router.post("/keyframes/{keyframe_id}/image")
async def upload_keyframe_image(
    keyframe_id: uuid.UUID = Path(...),
    file: UploadFile = File(..., description="关键帧图片（png/jpg/jpeg/webp）"),
    ctx: UserContext = Depends(get_user_context),
):
    """上传/替换关键帧图片：存入 story/keyframes/<项目名>/<关键帧名>/ 目录。

    文件经静态挂载 {BASE_URL}/public/files/{image_file} 可直接预览；
    替换时旧图自动清理。
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
    return R.success(
        data=await _keyframe_service.set_image(ctx, keyframe_id, data, ext)
    )


@router.delete("/keyframes/{keyframe_id}")
async def delete_keyframe(
    keyframe_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """删除关键帧：清理出场角色与编排引用。"""
    await _keyframe_service.delete(ctx, keyframe_id)
    return R.success()


@router.put("/keyframes/{keyframe_id}/characters")
async def set_keyframe_characters(
    keyframe_id: uuid.UUID = Path(...),
    payload: KeyframeCharactersRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """整体设置关键帧出场角色（参考立绘 + 局部描述），返回关键帧详情。"""
    return R.success(
        data=await _keyframe_service.set_characters(
            ctx, keyframe_id, payload.characters
        )
    )
