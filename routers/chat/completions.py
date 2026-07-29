"""
AI 流式问答路由：SSE 问答与停止生成。

SSE 帧为标准三字段（id / event / data），事件类型 think / answer / sources /
done / error（见 agent.constants.enums.chat.SseEvent）；帧构造与图执行编排
收口在 service.rag.chat.ChatCompletionService，本层只做请求解析与响应封装。
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, Path
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from service.rag.chat import ChatCompletionService, cancel_generation
from utils.response import R
from utils.user_context import UserContext, get_user_context

# 创建路由
router = APIRouter(prefix="/chat", tags=["OpenAPI - AI 问答"])

_service = ChatCompletionService()


class ChatCompletionRequest(BaseModel):
    """流式问答请求体。

    - session_id 缺省时服务端自动创建会话，并在首个 think 帧回传其 id；
    - kb_ids 为消息级检索范围（hex 无连字符列表），缺省按当前用户
      缺省可见范围解析；
    - use_web_search 联网搜索开关（暂未实现，透传给图）。
    """

    question: str
    session_id: Optional[uuid.UUID] = None
    kb_ids: Optional[list[str]] = None
    use_web_search: bool = False


@router.post("/completions")
async def chat_completions(
    payload: ChatCompletionRequest = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """流式问答（SSE）：帧含标准 id/event/data，事件 think/answer/sources/done/error。"""
    frames = await _service.stream(
        ctx,
        question=payload.question,
        session_id=payload.session_id,
        kb_ids=payload.kb_ids,
        use_web_search=payload.use_web_search,
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
