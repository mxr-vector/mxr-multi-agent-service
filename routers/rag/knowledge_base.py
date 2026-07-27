import uuid
from typing import Optional

from fastapi import APIRouter, Body, Path, Query
from pydantic import BaseModel

from service.rag.knowledge_base import KnowledgeBaseService
from utils.response import R

# 创建路由
router = APIRouter(prefix="/rag/knowledge-base", tags=["OpenAPI - RAG 知识库管理"])

_service = KnowledgeBaseService()


class KnowledgeBaseCreate(BaseModel):
    """创建知识库请求体（仅元数据，不创建 Qdrant collection；dept_id 由服务端注入）。

    qdrant_collection 由后端由 id 派生，不在请求体中暴露。
    """

    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_dim: Optional[int] = None
    visibility: str = "private"
    owner: Optional[str] = None


class KnowledgeBaseUpdate(BaseModel):
    """更新知识库请求体（仅可编辑元数据；dept_id/qdrant_collection/embedding_* 不可变）。"""

    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    visibility: Optional[str] = None
    owner: Optional[str] = None
    status: Optional[str] = None


@router.post("")
async def create_knowledge_base(payload: KnowledgeBaseCreate = Body(...)):
    """创建知识库（仅元数据，dept_id 服务端默认注入）。"""
    kb = await _service.create(
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        embedding_provider=payload.embedding_provider,
        embedding_model=payload.embedding_model,
        embedding_dim=payload.embedding_dim,
        visibility=payload.visibility,
        owner=payload.owner,
    )
    return R.success(data=kb)


@router.get("")
async def list_knowledge_bases(
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    size: int = Query(default=20, ge=1, le=200, description="每页数量"),
    keyword: Optional[str] = Query(default=None, description="按名称/描述模糊搜索"),
):
    """分页列出知识库（排除软删除的），可选按 keyword 过滤。"""
    page_result = await _service.list(page=page, size=size, keyword=keyword)
    return R.success(data=page_result)


@router.get("/{kb_id}")
async def get_knowledge_base(kb_id: uuid.UUID = Path(...)):
    """按 id 获取知识库。"""
    kb = await _service.get(kb_id)
    return R.success(data=kb)


@router.put("/{kb_id}")
async def update_knowledge_base(
    kb_id: uuid.UUID = Path(...),
    payload: KnowledgeBaseUpdate = Body(...),
):
    """仅元数据更新（含 status active↔archived）；不可变字段不受影响。"""
    changes = payload.model_dump(exclude_unset=True)
    kb = await _service.update(kb_id, changes)
    return R.success(data=kb)


@router.delete("/{kb_id}")
async def delete_knowledge_base(kb_id: uuid.UUID = Path(...)):
    """软删除：置 status='deleted'，随后不再出现在列表中。"""
    await _service.delete(kb_id)
    return R.success(msg="删除成功")
