"""
AI 问答会话管理路由：会话 CRUD、消息历史与统计。

问答历史为个人数据：服务层一律按当前用户 username 等值收敛，
他人会话按不存在处理；所有展示数据来自业务表（不读 checkpoint）。
注意 /stats 必须声明在 GET /{session_id} 之前，否则 "stats" 会被当作 UUID 解析。
"""

import uuid

from fastapi import APIRouter, Depends, Path, Query

from service.rag.chat import ChatSessionService
from utils.response import R
from utils.user_context import UserContext, get_user_context

# 创建路由
router = APIRouter(prefix="/chat/sessions", tags=["OpenAPI - AI 问答会话"])

_service = ChatSessionService()


@router.post("")
async def create_session(ctx: UserContext = Depends(get_user_context)):
    """创建会话（占位标题，首轮问答后由摘要任务回填）。"""
    chat_session = await _service.create(ctx)
    return R.success(data=chat_session)


@router.get("")
async def list_sessions(
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    size: int = Query(default=20, ge=1, le=200, description="每页数量"),
    ctx: UserContext = Depends(get_user_context),
):
    """分页列出本人会话（排除已删除），按最后消息时间倒序。"""
    page_result = await _service.list(ctx, page=page, size=size)
    return R.success(data=page_result)


# 注意：/stats 必须声明在 GET /{session_id} 之前
@router.get("/stats")
async def session_stats(ctx: UserContext = Depends(get_user_context)):
    """本人会话统计：会话总数与消息总数。"""
    stats = await _service.stats(ctx)
    return R.success(data=stats)


@router.get("/{session_id}")
async def get_session(
    session_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """会话详情（仅属主可见）。"""
    chat_session = await _service.get(ctx, session_id)
    return R.success(data=chat_session)


@router.get("/{session_id}/messages")
async def list_session_messages(
    session_id: uuid.UUID = Path(...),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    size: int = Query(default=50, ge=1, le=200, description="每页数量"),
    ctx: UserContext = Depends(get_user_context),
):
    """会话消息历史（仅属主可见），按 sequence 升序分页。"""
    page_result = await _service.messages(ctx, session_id, page=page, size=size)
    return R.success(data=page_result)


@router.delete("/{session_id}")
async def delete_session(
    session_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """删除会话：软删业务表并同步清理 checkpoint thread；在途生成任务先取消。"""
    await _service.delete(ctx, session_id)
    return R.success(msg="删除成功")


@router.delete("")
async def delete_all_sessions(ctx: UserContext = Depends(get_user_context)):
    """清空本人全部会话（软删 + checkpoint thread 清理）。"""
    count = await _service.delete_all(ctx)
    return R.success(data={"deleted": count})
