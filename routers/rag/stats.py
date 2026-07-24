from fastapi import APIRouter

from service.rag.stats import StatsService
from utils.response import R

# 创建路由
router = APIRouter(prefix="/rag/stats", tags=["OpenAPI - RAG 统计"])

_service = StatsService()


@router.get("")
async def get_rag_stats():
    """返回 RAG 全局统计：知识库数、文档总数、分块总数（均排除软删除的知识库）。"""
    overview = await _service.overview()
    return R.success(data=overview)
