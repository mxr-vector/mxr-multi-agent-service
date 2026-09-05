"""
绘图模块路由：SSE 生成、图片上传、会话/版本查询、编辑保存。

SSE 帧为标准三字段（id / event / data），事件类型 think / answer / done / error
（复用 agent.constants.enums.chat.SseEvent，与 chat 问答格式一致）；帧构造与
模型编排收口在 service.draw.diagram，本层只做请求解析与响应封装。
"""

import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, Path, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from uuid_utils.compat import uuid7

from exception.bad_except import bad_except
from service.draw.diagram import (
    IMAGE_EXTENSION_MIME,
    DrawCompletionService,
    DrawSessionService,
    cancel_generation,
)
from utils.env import ENV
from utils.page import build_page_result
from utils.response import R
from utils.user_context import UserContext, get_user_context
from utils.file_ingest import read_upload_capped

# 创建路由
router = APIRouter(prefix="/draw", tags=["OpenAPI - AI 绘图"])

_completion_service = DrawCompletionService()
_session_service = DrawSessionService()

# 上传图片大小上限：沿用全局上传守卫配置
_IMAGE_SUBDIR = "draw/upload"
_PREVIEW_SUBDIR = "draw/preview"


class DrawCompletionRequest(BaseModel):
    """流式生成请求体。

    - question 与 image_file 至少其一非空（图片可不附文字，按缺省指令重绘）；
    - session_id 缺省时服务端自动创建会话，并在首个 think 帧回传其 id；
    - image_file 为上传端点返回的 data/ 下相对路径（如 draw/upload/xxx.png）；
    - base_version_id 为多轮改图基线版本 id：模型基于其 Mermaid 源修改，
      新 AI 版本的 parent_id 指向它。
    """

    question: str = ""
    session_id: Optional[uuid.UUID] = None
    image_file: Optional[str] = None
    base_version_id: Optional[uuid.UUID] = None


@router.post("/completions")
async def draw_completions(
    payload: DrawCompletionRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """流式生成（SSE）：帧含标准 id/event/data，事件 think/answer/done/error。"""
    frames = await _completion_service.stream(
        ctx,
        question=payload.question,
        session_id=payload.session_id,
        image_file=payload.image_file,
        base_version_id=payload.base_version_id,
    )
    return StreamingResponse(
        frames,
        media_type="text/event-stream",
        headers={
            # 禁用代理缓冲（nginx 等），保证帧即时到达
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/stop/{session_id}")
async def stop_generation(
    session_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """停止生成：取消该会话在途生成任务（推理即刻中止）；无在途任务幂等成功。"""
    cancelled = cancel_generation(session_id.hex)
    return R.success(data={"cancelled": cancelled})


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(..., description="待重绘的图片（png/jpg/jpeg/webp）"),
    ctx: UserContext = Depends(get_user_context),
):
    """上传图片：类型白名单 + 大小校验后存 data/draw/upload，返回相对路径。

    返回的 image_file 用于后续 /draw/completions 请求；文件经静态挂载
    {BASE_URL}/public/files/{image_file} 可直接预览。
    """
    ext = (
        file.filename.rsplit(".", 1)[-1].lower()
        if file.filename and "." in file.filename
        else ""
    )
    if ext not in IMAGE_EXTENSION_MIME:
        bad_except(
            f"不支持的图片类型: {file.filename or '(无扩展名)'}（仅 png/jpg/jpeg/webp）"
        )
    # 分块读取并即时校验（Content-Length 可伪造），超限在载入全量内存前即拒绝
    data = await read_upload_capped(file, ENV.upload_max_size_mb * 1024 * 1024)

    relative = f"{_IMAGE_SUBDIR}/{uuid7().hex}.{ext}"
    target = ENV.upload_dir / relative

    def _save() -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    await asyncio.to_thread(_save)
    return R.success(data={"image_file": relative})


@router.get("/sessions")
async def list_sessions(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    ctx: UserContext = Depends(get_user_context),
):
    """分页列出本人绘图会话，按最后消息时间倒序。"""
    items, total = await _session_service.list(ctx, page, size)
    return R.success(data=build_page_result(items, total, page, size))


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    session_id: uuid.UUID = Path(...),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    ctx: UserContext = Depends(get_user_context),
):
    """会话消息历史，按 sequence 升序分页。"""
    items, total = await _session_service.messages(ctx, session_id, page, size)
    return R.success(data=build_page_result(items, total, page, size))


@router.get("/sessions/{session_id}/versions")
async def list_versions(
    session_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """会话图表版本链（创建时间升序），不携带 drawio_xml。"""
    items = await _session_service.versions(ctx, session_id)
    return R.success(data=items)


@router.get("/versions/{version_id}")
async def version_detail(
    version_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """版本详情（携带 drawio_xml），供 drawio 编辑器加载。"""
    return R.success(data=await _session_service.version_detail(ctx, version_id))


@router.post("/versions")
async def save_version(
    session_id: uuid.UUID = Form(..., description="所属绘图会话 id"),
    parent_id: uuid.UUID = Form(..., description="本次编辑的基线版本 id"),
    drawio_xml: str = Form(..., description="编辑器导出的 drawio XML"),
    preview: Optional[UploadFile] = File(
        default=None, description="编辑器导出的 xmlpng 预览（内嵌 XML 的 PNG）"
    ),
    ctx: UserContext = Depends(get_user_context),
):
    """drawio 编辑保存：append-only 新增 user 来源版本，基线版本保持不变。"""
    preview_file: str | None = None
    if preview is not None:
        data = await preview.read()
        max_bytes = ENV.upload_max_size_mb * 1024 * 1024
        if len(data) > max_bytes:
            bad_except(f"预览图超过大小上限（{ENV.upload_max_size_mb}MB）")
        preview_file = f"{_PREVIEW_SUBDIR}/{uuid7().hex}.png"
        target = ENV.upload_dir / preview_file

        def _save() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        await asyncio.to_thread(_save)

    version = await _session_service.save_edit(
        ctx,
        session_id=session_id,
        parent_id=parent_id,
        drawio_xml=drawio_xml,
        preview_file=preview_file,
    )
    return R.success(data=version)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """删除会话：同事务清理消息与版本记录。"""
    await _session_service.delete(ctx, session_id)
    return R.success()
