"""
剧本生成路由：风格枚举、SSE 流式生成、停止生成与任务查询。

SSE 帧为标准三字段（id/event/data），事件 think/answer/done/error；
帧构造与生成编排收口在 service.story.generation，本层只做请求解析与响应封装。
"""

import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Path, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from exception.bad_except import bad_except
from service.story.generation import StoryGenerationService
from service.story.session import StorySessionService
from service.story.storage import IMAGE_EXTENSIONS, save_story_upload
from utils.env import ENV
from utils.file_ingest import read_upload_capped
from utils.response import R
from utils.user_context import UserContext, get_user_context

router = APIRouter(prefix="/story", tags=["OpenAPI - 剧本生成"])

_session_service = StorySessionService()
_generation_service = StoryGenerationService()


class ScriptGenerateRequest(BaseModel):
    """剧本生成请求体。

    - style_key 须为风格注册表已注册风格（未注册拒绝且不发起模型调用）；
    - aspect_ratio 缺省取该风格首选画幅；传值不在该风格预设内时拒绝；
    - episodes/tone 可选，随制作参数快照落库并回写项目；
    - image_file/images 可选，上传给多模态大模型的参考图片相对路径。
    """

    # idea 不参与历史裁剪（idea_block 恒全量发送），限制合理长度上限防超长输入
    # 击穿输入预算致上游 400 且单请求 token 成本不可控；支持丰富的故事设定与长提示词
    idea: str = Field(max_length=20000, description="创作需求/提示词")
    style_key: str
    aspect_ratio: Optional[str] = None
    episodes: Optional[int] = Field(default=None, ge=1, le=100)
    tone: Optional[str] = None
    image_file: Optional[str] = Field(default=None, description="主图片相对路径")
    images: Optional[list[str]] = Field(default=None, description="多模态输入图片相对路径列表")


@router.post("/upload-image")
async def upload_story_image(
    file: UploadFile = File(..., description="上传图片（支持 png/jpg/jpeg/webp）"),
    ctx: UserContext = Depends(get_user_context),
):
    """故事模块通用图片上传：供大模型多模态对话或生图参考图使用。"""
    ext = (
        file.filename.rsplit(".", 1)[-1].lower()
        if file.filename and "." in file.filename
        else ""
    )
    if ext not in IMAGE_EXTENSIONS:
        bad_except(
            f"不支持的图片类型: {file.filename or '(无扩展名)'}（仅支持 {', '.join(sorted(IMAGE_EXTENSIONS))}）"
        )
    data = await read_upload_capped(file, ENV.upload_max_size_mb * 1024 * 1024)
    relative = await asyncio.to_thread(
        save_story_upload, ctx.user_id or "common", file.filename or f"upload.{ext}", data
    )
    return R.success(
        data={
            "image_file": relative,
            "url": f"{ENV.base_url}/public/files/{relative}",
        }
    )


@router.get("/styles")
async def list_styles(
    ctx: UserContext = Depends(get_user_context),
):
    """视频风格注册表枚举（生成表单数据源：风格名/描述/画幅预设）。"""
    from agent.skills.loader import list_styles

    return R.success(data=list_styles())


@router.post("/sessions/{session_id}/generate")
async def generate_script(
    session_id: uuid.UUID = Path(...),
    payload: ScriptGenerateRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """流式剧本生成（SSE）：done 帧携带角色卡与降级信息。"""
    frames = await _generation_service.stream(
        ctx,
        session_id=session_id,
        idea=payload.idea,
        style_key=payload.style_key,
        aspect_ratio=payload.aspect_ratio,
        episodes=payload.episodes,
        tone=payload.tone,
        image_file=payload.image_file,
        images=payload.images,
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


@router.post("/sessions/{session_id}/stop")
async def stop_generation(
    session_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """停止生成：取消该会话在途生成任务（推理即刻中止）；无在途任务幂等成功。"""
    cancelled = await _generation_service.stop(ctx, session_id)
    return R.success(data={"cancelled": cancelled})


@router.get("/projects/{project_id}/generation-tasks")
async def list_generation_tasks(
    project_id: uuid.UUID = Path(...),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    ctx: UserContext = Depends(get_user_context),
):
    """项目生成任务分页列表（创建时间倒序，可按状态过滤）。"""
    return R.success(
        data=await _generation_service.list_tasks(ctx, project_id, page, size, status)
    )


@router.get("/generation-tasks/{task_id}")
async def generation_task_detail(
    task_id: uuid.UUID = Path(...),
    with_result_text: bool = Query(default=False, description="是否携带剧本全文"),
    ctx: UserContext = Depends(get_user_context),
):
    """生成任务详情（默认不含 result_text 长文本，按需开启）。"""
    return R.success(
        data=await _generation_service.task_detail(
            ctx, task_id, with_result_text=with_result_text
        )
    )
