"""
剧本模块项目路由：项目 CRUD 与详情。

剧本/关键帧/导出/视频等子资源路由按域拆分在同包其它模块，
统一嵌套在 /story/projects/{project_id} 之下。
"""

import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel

from agent.constants.enums.story import StoryProjectStatus
from service.story.project import ProjectService
from utils.page import build_page_result
from utils.response import R
from utils.user_context import UserContext, get_user_context

router = APIRouter(prefix="/story", tags=["OpenAPI - 剧本项目管理"])

_project_service = ProjectService()


class ProjectCreateRequest(BaseModel):
    """创建项目请求体：标题缺省"新剧本"。"""

    title: Optional[str] = None
    description: Optional[str] = None


class ProjectUpdateRequest(BaseModel):
    """更新项目请求体：仅显式传入的字段生效。"""

    title: Optional[str] = None
    description: Optional[str] = None
    cover_image: Optional[str] = None
    status: Optional[str] = None  # 'active'/'archived'


@router.get("/projects")
async def list_projects(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    keyword: Optional[str] = Query(default=None, description="标题模糊检索"),
    status: Optional[StoryProjectStatus] = Query(
        default=None,
        description="按状态过滤（仅 active/archived；软删项目列表不可见）",
    ),
    ctx: UserContext = Depends(get_user_context),
):
    """分页列出本人项目，更新时间倒序。"""
    items, total = await _project_service.list(ctx, page, size, keyword, status)
    return R.success(data=build_page_result(items, total, page, size))


@router.post("/projects")
async def create_project(
    payload: ProjectCreateRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """创建项目（归属当前用户）。"""
    return R.success(data=await _project_service.create(ctx, payload))


@router.get("/projects/{project_id}")
async def project_detail(
    project_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """项目详情：本体 + 冗余计数 + 当前剧本摘要。"""
    return R.success(data=await _project_service.detail(ctx, project_id))


@router.put("/projects/{project_id}")
async def update_project(
    project_id: uuid.UUID = Path(...),
    payload: ProjectUpdateRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """更新项目字段（标题/描述/封面/状态）。"""
    return R.success(data=await _project_service.update(ctx, project_id, payload))


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """软删项目（列表不可见，资产行保留）。"""
    await _project_service.delete(ctx, project_id)
    return R.success()
