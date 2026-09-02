"""
剧本模块剧本路由：多版本保存、历史列表与当前版本切换。
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel

from service.story.script import ScriptService
from utils.page import build_page_result
from utils.response import R
from utils.user_context import UserContext, get_user_context

router = APIRouter(prefix="/story", tags=["OpenAPI - 剧本版本"])

_script_service = ScriptService()


class ScriptSaveRequest(BaseModel):
    """保存新剧本版本请求体。"""

    content: str
    title: Optional[str] = None
    source: str = "user"  # 'ai'/'user'/'upload'
    set_current: bool = False  # 首版无需指定，自动成为当前版本


class ScriptUpdateRequest(BaseModel):
    """编辑既有版本请求体（来源将标记为 user）。"""

    content: Optional[str] = None
    title: Optional[str] = None


@router.get("/projects/{project_id}/scripts")
async def list_scripts(
    project_id: uuid.UUID = Path(...),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=100),
    ctx: UserContext = Depends(get_user_context),
):
    """项目剧本历史列表，版本号倒序。"""
    items, total = await _script_service.list(ctx, project_id, page, size)
    return R.success(data=build_page_result(items, total, page, size))


@router.post("/projects/{project_id}/scripts")
async def save_script(
    project_id: uuid.UUID = Path(...),
    payload: ScriptSaveRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """保存新剧本版本：版本号项目内递增；首版或显式指定时置为当前版本。"""
    return R.success(data=await _script_service.save(ctx, project_id, payload))


@router.put("/scripts/{script_id}/current")
async def switch_current_script(
    script_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """切换当前版本：先复位项目全部剧本再置位所选版本。"""
    return R.success(data=await _script_service.switch_current(ctx, script_id))


@router.put("/scripts/{script_id}")
async def update_script(
    script_id: uuid.UUID = Path(...),
    payload: ScriptUpdateRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """编辑既有版本内容/标题。"""
    return R.success(data=await _script_service.update(ctx, script_id, payload))
