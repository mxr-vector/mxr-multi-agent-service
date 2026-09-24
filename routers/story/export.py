"""
剧本模块导出包路由：统一格式装配与历史查询。
"""

import urllib.parse
import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, Path, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from service.story.export import ExportService
from utils.page import build_page_result
from utils.response import R
from utils.user_context import UserContext, get_user_context

router = APIRouter(prefix="/story", tags=["OpenAPI - 剧本导出包"])

_export_service = ExportService()


class ExportRequest(BaseModel):
    """导出请求体：均可空（名称缺省自动生成，平台仅备注）。"""

    name: Optional[str] = None
    target_platform: Optional[str] = None  # 自由文本备注，不做字典


@router.post("/projects/{project_id}/exports")
async def create_export(
    project_id: uuid.UUID = Path(...),
    payload: ExportRequest = Body(default=ExportRequest()),
    ctx: UserContext = Depends(get_user_context),
):
    """生成导出包：当前剧本 + 出演角色 + 被选关键帧，统一格式不可变快照。"""
    return R.success(data=await _export_service.export(ctx, project_id, payload))


@router.get("/projects/{project_id}/exports")
async def list_exports(
    project_id: uuid.UUID = Path(...),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    ctx: UserContext = Depends(get_user_context),
):
    """项目导出包列表，版本倒序。"""
    items, total = await _export_service.list(ctx, project_id, page, size)
    return R.success(data=build_page_result(items, total, page, size))


@router.get("/exports/{package_id}")
async def export_detail(
    package_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """导出包详情（含素材快照清单）。"""
    return R.success(data=await _export_service.detail(ctx, package_id))


@router.get("/exports/{package_id}/download")
async def download_export(
    package_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """下载导出包 ZIP 文件（含剧本、关键帧、人物立绘及完整说明）。"""
    buffer, filename = await _export_service.build_zip(ctx, package_id)
    encoded_filename = urllib.parse.quote(filename)
    data = buffer.getvalue()
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=\"export.zip\"; filename*=utf-8''{encoded_filename}",
            "Content-Length": str(len(data)),
            "Access-Control-Expose-Headers": "Content-Disposition, Content-Length",
        },
    )
