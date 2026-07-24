import uuid
from typing import Optional

from fastapi import APIRouter, Path, Query

from service.rag.chunks import ChunkService
from utils.response import R

# 创建路由
router = APIRouter(prefix="/rag/chunks", tags=["OpenAPI - RAG 文档分块管理"])

_service = ChunkService()


@router.get("")
async def list_chunks(
    document_id: uuid.UUID = Query(..., description="按文档过滤"),
    level: Optional[int] = Query(
        default=None, description="按层级过滤（0 叶块 / 1 父块）"
    ),
    document_version: Optional[int] = Query(default=None, description="按文档版本过滤"),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    size: int = Query(default=50, ge=1, le=200, description="每页数量"),
):
    """按文档分页列出分块，可选 level/document_version 过滤，按 chunk_index 升序。"""
    page_result = await _service.list(
        document_id,
        level=level,
        document_version=document_version,
        page=page,
        size=size,
    )
    return R.success(data=page_result)


@router.get("/{chunk_id}")
async def get_chunk(chunk_id: uuid.UUID = Path(...)):
    """按 id 获取分块。"""
    chunk = await _service.get(chunk_id)
    return R.success(data=chunk)
