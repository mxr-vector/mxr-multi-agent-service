"""
剧本模块生成会话路由：会话创建/列表/详情/删除与消息历史。

会话创建与列表嵌套在 /story/projects/{project_id}/sessions 之下（项目作用域），
详情/消息/删除按会话 id 直达（属主校验经项目收敛，见服务层）。
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel

from service.story.session import StorySessionService
from utils.response import R
from utils.user_context import UserContext, get_user_context

router = APIRouter(prefix="/story", tags=["OpenAPI - 剧本生成会话"])

_session_service = StorySessionService()


class SessionCreateRequest(BaseModel):
    """创建会话请求体：类型缺省 general。"""

    title: Optional[str] = None
    type: str = "general"  # 'general'/'script'/'character'/'character_art'/'keyframe'


@router.post("/projects/{project_id}/sessions")
async def create_session(
    project_id: uuid.UUID = Path(...),
    payload: SessionCreateRequest = Body(default=SessionCreateRequest()),
    ctx: UserContext = Depends(get_user_context),
):
    """创建生成会话（归属项目属主）。"""
    return R.success(data=await _session_service.create(ctx, project_id, payload))


@router.get("/projects/{project_id}/sessions")
async def list_sessions(
    project_id: uuid.UUID = Path(...),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    ctx: UserContext = Depends(get_user_context),
):
    """分页列出项目下生成会话，最近活跃倒序。"""
    return R.success(
        data=await _session_service.list(ctx, project_id, page, size)
    )


@router.get("/projects/{project_id}/sessions/latest")
async def latest_session(
    project_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """项目最近活跃会话（抽屉默认打开目标；无会话时 data 为 null）。"""
    return R.success(data=await _session_service.latest(ctx, project_id))


@router.get("/sessions/{session_id}")
async def session_detail(
    session_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """会话详情（仅属主可见）。"""
    return R.success(data=await _session_service.detail(ctx, session_id))


@router.get("/sessions/{session_id}/messages")
async def list_session_messages(
    session_id: uuid.UUID = Path(...),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    ctx: UserContext = Depends(get_user_context),
):
    """会话消息历史（仅属主可见），按 sequence 升序分页。"""
    return R.success(
        data=await _session_service.messages(ctx, session_id, page, size)
    )


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """删除会话：未沉淀的生成结果随之丢弃；已沉淀正式资产不受影响。"""
    await _session_service.delete(ctx, session_id)
    return R.success()
