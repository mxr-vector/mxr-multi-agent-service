"""
剧本模块产物沉淀路由：立绘生成、角色卡编辑与"存为版本/存入角色库"。

全部以会话消息 id 为锚点（属主经项目收敛）；沉淀后产物进入既有正式
资产 API（剧本版本/角色库/出演登记）的可见范围。
"""

import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel, Field

from service.story.art import ArtGenerationService
from service.story.sediment import SedimentService
from utils.response import R
from utils.user_context import UserContext, get_user_context

router = APIRouter(prefix="/story", tags=["OpenAPI - 剧本产物沉淀"])

_art_service = ArtGenerationService()
_sediment_service = SedimentService()


class ArtGenerateRequest(BaseModel):
    """立绘生成请求体：size/quality 缺省取 image 角色配置。"""

    size: Optional[str] = None
    quality: Optional[str] = None


class DirectArtGenerateRequest(BaseModel):
    """直接立绘生成请求体。"""

    prompt: str = Field(..., min_length=1, max_length=4000, description="出图提示词")
    name: Optional[str] = Field(default=None, description="角色名/立绘标题")
    card_message_id: Optional[uuid.UUID] = Field(default=None, description="可选关联的角色卡消息 ID")
    size: Optional[str] = None
    quality: Optional[str] = None


class CardEditRequest(BaseModel):
    """角色卡编辑请求体：仅显式传入的白名单字段生效。"""

    name: Optional[str] = None
    role_type: Optional[
        Literal["protagonist", "supporting", "antagonist", "npc", "other"]
    ] = None
    profile: Optional[dict] = None
    visual_profile: Optional[dict] = None
    appearance_prompt: Optional[str] = None
    art_prompt: Optional[str] = None
    negative_prompt: Optional[str] = None


class ScriptSedimentRequest(BaseModel):
    """剧本沉淀请求体：可命名版本并选择设为当前版本。"""

    title: Optional[str] = None
    set_current: bool = False


class CharacterSedimentRequest(BaseModel):
    """角色沉淀请求体：同名角色由前端先行提示，服务端按 mode 执行。

    - mode='new' 新建角色库角色；
    - mode='merge' 并入 character_id 指向的既有角色（仅新增立绘与出演登记）。
    - art_message_ids: 指定收编的立绘消息列表，缺省为收编全部未沉淀立绘。
    """

    mode: Literal["new", "merge"] = "new"
    character_id: Optional[uuid.UUID] = None
    art_message_ids: Optional[list[uuid.UUID]] = None


class ArtSedimentRequest(BaseModel):
    """单个立绘沉淀请求体：可指定归属的角色 id，缺省时自动关联角色卡或同名角色。"""

    character_id: Optional[uuid.UUID] = None


@router.post("/messages/{message_id}/generate-art")
async def generate_art(
    message_id: uuid.UUID = Path(...),
    payload: ArtGenerateRequest = Body(default=ArtGenerateRequest()),
    ctx: UserContext = Depends(get_user_context),
):
    """从角色卡发起内部立绘生成：返回生成任务记录（前端轮询任务详情）。"""
    return R.success(
        data=await _art_service.start(
            ctx, message_id=message_id, size=payload.size, quality=payload.quality
        )
    )


@router.post("/sessions/{session_id}/generate-art")
async def generate_session_art(
    session_id: uuid.UUID = Path(...),
    payload: DirectArtGenerateRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """直接在会话中根据提示词发起人物立绘生成任务。"""
    return R.success(
        data=await _art_service.start_direct(
            ctx,
            session_id=session_id,
            prompt=payload.prompt,
            name=payload.name,
            card_message_id=payload.card_message_id,
            size=payload.size,
            quality=payload.quality,
        )
    )


@router.put("/messages/{message_id}/card")
async def edit_card(
    message_id: uuid.UUID = Path(...),
    payload: CardEditRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """编辑角色卡字段（沉淀前修订；沉淀以修订后内容入库）。"""
    return R.success(
        data=await _sediment_service.edit_card(ctx, message_id, payload.model_dump(exclude_unset=True))
    )


@router.post("/messages/{message_id}/save-script")
async def save_script(
    message_id: uuid.UUID = Path(...),
    payload: ScriptSedimentRequest = Body(default=ScriptSedimentRequest()),
    ctx: UserContext = Depends(get_user_context),
):
    """剧本卡存为项目剧本新版本（source='ai'，重复沉淀产生新版本）。"""
    return R.success(
        data=await _sediment_service.save_script(
            ctx, message_id, payload.title, payload.set_current
        )
    )


@router.post("/messages/{message_id}/save-character")
async def save_character(
    message_id: uuid.UUID = Path(...),
    payload: CharacterSedimentRequest = Body(default=CharacterSedimentRequest()),
    ctx: UserContext = Depends(get_user_context),
):
    """角色卡存入角色库（单事务：建角色/并入 + 立绘收编 + 自动出演登记）。"""
    return R.success(
        data=await _sediment_service.save_character(
            ctx, message_id, payload.mode, payload.character_id, payload.art_message_ids
        )
    )


@router.post("/messages/{message_id}/save-art")
async def save_art(
    message_id: uuid.UUID = Path(...),
    payload: ArtSedimentRequest = Body(default=ArtSedimentRequest()),
    ctx: UserContext = Depends(get_user_context),
):
    """单个立绘消息存入角色库（可指定角色或自动归属关联角色卡）。"""
    return R.success(
        data=await _sediment_service.save_art(ctx, message_id, payload.character_id)
    )


@router.post("/messages/{message_id}/save-keyframe")
async def save_keyframe(
    message_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """关键帧卡存入项目的关键帧库（若已存在同场景-镜头则更新）。"""
    return R.success(
        data=await _sediment_service.save_keyframe(ctx, message_id)
    )


@router.post("/sessions/{session_id}/save-keyframes")
async def save_all_keyframes(
    session_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """一键将当前会话中的全部关键帧存入项目关键帧库。"""
    return R.success(
        data=await _sediment_service.save_all_keyframes(ctx, session_id)
    )


