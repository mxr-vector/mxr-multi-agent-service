from typing import Optional

from fastapi import APIRouter, Depends, Query

from service.rag.stats import StatsService
from utils.response import R
from utils.user_context import UserContext, get_user_context

# 创建路由
router = APIRouter(prefix="/rag/stats", tags=["OpenAPI - RAG 统计"])

_service = StatsService()


@router.get("")
async def get_rag_stats(
    dept_ids: Optional[list[str]] = Query(
        default=None,
        description="按部门过滤（可重复传参，32 位 hex；仅 data_scope=all 生效）",
    ),
    ctx: UserContext = Depends(get_user_context),
):
    """返回 RAG 统计：知识库数、文档总数、分块总数（口径与知识库列表的部门边界一致）。"""
    overview = await _service.overview(ctx, dept_ids=dept_ids)
    return R.success(data=overview)
