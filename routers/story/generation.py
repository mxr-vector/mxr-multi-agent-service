"""
剧本生成路由：风格枚举、SSE 流式生成、停止生成与任务查询。

SSE 帧为标准三字段（id/event/data），事件 think/answer/done/error；
帧构造与生成编排收口在 service.story.generation，本层只做请求解析与响应封装。
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, Path, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from service.story.generation import StoryGenerationService
from service.story.session import StorySessionService
from utils.response import R
from utils.user_context import UserContext, get_user_context

router = APIRouter(prefix="/story", tags=["OpenAPI - 剧本生成"])

_session_service = StorySessionService()
_generation_service = StoryGenerationService()


class ScriptGenerateRequest(BaseModel):
    """剧本生成请求体。

    - style_key 须为风格注册表已注册风格（未注册拒绝且不发起模型调用）；
    - aspect_ratio 缺省取该风格首选画幅；传值不在该风格预设内时拒绝；
    - episodes/tone 可选，随制作参数快照落库并回写项目。
    """

    # idea 不参与历史裁剪（idea_block 恒全量发送），必须限制长度防超长输入
    # 击穿输入预算致上游 400 且单请求 token 成本不可控
    idea: str = Field(max_length=4000)
    style_key: str
    aspect_ratio: Optional[str] = None
    episodes: Optional[int] = None
    tone: Optional[str] = None


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
