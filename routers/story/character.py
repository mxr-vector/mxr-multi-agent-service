"""
剧本模块角色库路由：角色 CRUD、立绘上传与主立绘、项目出演登记。

出演登记语义上属于项目作用域，但引用对象与删除守卫均为角色库行为，
统一由本模块出路由，路径嵌套在 /story/projects/{project_id}/characters 下。
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, Path, Query, UploadFile
from pydantic import BaseModel

from exception.bad_except import bad_except
from service.story.character import CastingService, CharacterService
from service.story.storage import IMAGE_EXTENSIONS
from utils.env import ENV
from utils.page import build_page_result
from utils.response import R
from utils.user_context import UserContext, get_user_context
from utils.file_ingest import read_upload_capped

router = APIRouter(prefix="/story", tags=["OpenAPI - 剧本角色库"])

_character_service = CharacterService()
_casting_service = CastingService()

# 立绘图片白名单复用 storage.IMAGE_EXTENSIONS（对齐 draw 上传守卫：类型白名单 + 大小上限）；
# 落盘路径由业务层按用户命名空间目录决定（UPLOAD_DIR/story/characters/<user_id>/<角色名>）

# 出演角色排序上限（防异常大列表）
_CAST_SORT_MAX = 200


class CharacterCreateRequest(BaseModel):
    """创建角色请求体：名称必填，人设/风格为结构化 JSON。"""

    name: str
    role_type: Optional[str] = None
    profile: dict = {}
    style: dict = {}
    appearance_prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    avatar_file: Optional[str] = None


class CharacterUpdateRequest(BaseModel):
    """更新角色请求体：仅显式传入的白名单字段生效（可传 null 清空文本字段）。"""

    name: Optional[str] = None
    role_type: Optional[str] = None
    profile: Optional[dict] = None
    style: Optional[dict] = None
    appearance_prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    avatar_file: Optional[str] = None


class CastAddRequest(BaseModel):
    """出演登记请求体。"""

    character_id: uuid.UUID


class CastSortRequest(BaseModel):
    """出演排序请求体：按目标顺序给出全部出演角色 id。"""

    character_ids: list[uuid.UUID]


class ArtSelectionRequest(BaseModel):
    """立绘选择请求体：按顺序给出本项目选中的立绘 id（空列表清空）。"""

    art_ids: list[uuid.UUID]


@router.get("/characters")
async def list_characters(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    keyword: Optional[str] = Query(default=None, description="角色名模糊检索"),
    ctx: UserContext = Depends(get_user_context),
):
    """分页列出本人角色库，创建时间倒序。"""
    items, total = await _character_service.list(ctx, page, size, keyword)
    return R.success(data=build_page_result(items, total, page, size))


@router.post("/characters")
async def create_character(
    payload: CharacterCreateRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """创建角色（归属当前用户）。"""
    return R.success(data=await _character_service.create(ctx, payload))


@router.get("/characters/{character_id}")
async def character_detail(
    character_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """角色详情：本体 + 立绘列表 + 出演项目提示。"""
    return R.success(data=await _character_service.detail(ctx, character_id))


@router.put("/characters/{character_id}")
async def update_character(
    character_id: uuid.UUID = Path(...),
    payload: CharacterUpdateRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """更新角色字段（白名单内显式传入的字段）。"""
    return R.success(data=await _character_service.update(ctx, character_id, payload))


@router.delete("/characters/{character_id}")
async def delete_character(
    character_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """删除角色：被项目出演或被关键帧引用时拒绝。"""
    await _character_service.delete(ctx, character_id)
    return R.success()


@router.post("/characters/{character_id}/arts")
async def upload_art(
    character_id: uuid.UUID = Path(...),
    file: UploadFile = File(..., description="立绘图片（png/jpg/jpeg/webp）"),
    name: Optional[str] = Form(default=None, description="立绘名（如常服正面）"),
    art_type: str = Form(
        default="full_body",
        description="立绘类型：turnaround(三视图)/front_bust(正面半身特写)/"
        "full_body/half_body/face/action/reference/other",
    ),
    ctx: UserContext = Depends(get_user_context),
):
    """上传立绘：白名单 + 大小校验后存入角色名目录，返回立绘记录。

    首张立绘自动设为主立绘；文件经静态挂载 {BASE_URL}/public/files/{image_file}
    可直接预览。
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

    art = await _character_service.add_art(
        ctx, character_id, file_data=data, ext=ext, name=name, art_type=art_type
    )
    return R.success(data=art)


@router.put("/characters/{character_id}/arts/{art_id}/primary")
async def set_primary_art(
    character_id: uuid.UUID = Path(...),
    art_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """设主立绘：先复位原主立绘再置位，角色头像同步。"""
    return R.success(
        data=await _character_service.set_primary_art(ctx, character_id, art_id)
    )


@router.delete("/characters/{character_id}/arts/{art_id}")
async def delete_art(
    character_id: uuid.UUID = Path(...),
    art_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """删除立绘：删除主立绘时最早一张继任。"""
    await _character_service.delete_art(ctx, character_id, art_id)
    return R.success()


@router.get("/projects/{project_id}/characters")
async def list_casting(
    project_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """项目出演角色列表（含角色完整信息），按出演顺序升序。"""
    return R.success(data=await _casting_service.list(ctx, project_id))


@router.post("/projects/{project_id}/characters")
async def add_casting(
    project_id: uuid.UUID = Path(...),
    payload: CastAddRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """出演登记：引用角色库角色（非拷贝），重复登记拒绝。"""
    return R.success(
        data=await _casting_service.add(ctx, project_id, payload.character_id)
    )


@router.delete("/projects/{project_id}/characters/{character_id}")
async def remove_casting(
    project_id: uuid.UUID = Path(...),
    character_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """移除出演登记。"""
    await _casting_service.remove(ctx, project_id, character_id)
    return R.success()


@router.put("/projects/{project_id}/characters/sort")
async def sort_casting(
    project_id: uuid.UUID = Path(...),
    payload: CastSortRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """重排出演顺序：传入集合须与项目当前出演集合一致。"""
    if len(payload.character_ids) > _CAST_SORT_MAX:
        bad_except(f"出演角色数量超过上限（{_CAST_SORT_MAX}）")
    await _casting_service.sort(ctx, project_id, payload.character_ids)
    return R.success()


@router.put("/projects/{project_id}/art-selection")
async def set_art_selection(
    project_id: uuid.UUID = Path(...),
    payload: ArtSelectionRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """整体设置项目选中立绘（导出使用）；立绘须归属本项目出演角色。"""
    return R.success(
        data=await _casting_service.set_art_selection(ctx, project_id, payload.art_ids)
    )
