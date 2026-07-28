import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel

from service.rag.knowledge_base import KnowledgeBaseService
from utils.response import R
from utils.user_context import UserContext, get_user_context

# 创建路由
router = APIRouter(prefix="/rag/knowledge-base", tags=["OpenAPI - RAG 知识库管理"])

_service = KnowledgeBaseService()


class KnowledgeBaseCreate(BaseModel):
    """创建知识库请求体（仅元数据，不创建 Qdrant collection）。

    dept_id 仅 data_scope=all 生效（须为已存在部门，all 档必填），
    其余档位由服务端强制本人部门；知识库必须归属部门，
    无法解析出归属部门时服务端拒绝创建。
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
    dept_id: Optional[str] = None


class KnowledgeBaseUpdate(BaseModel):
    """更新知识库请求体（仅可编辑元数据；dept_id/qdrant_collection/embedding_* 不可变）。"""

    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    visibility: Optional[str] = None
    owner: Optional[str] = None
    status: Optional[str] = None


@router.post("")
async def create_knowledge_base(
    payload: KnowledgeBaseCreate = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """创建知识库（仅元数据；dept_id 仅 all 档尊重请求值，其余从用户上下文注入；
    归属部门不可为空，否则拒绝创建）。"""
    kb = await _service.create(
        ctx,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        embedding_provider=payload.embedding_provider,
        embedding_model=payload.embedding_model,
        embedding_dim=payload.embedding_dim,
        visibility=payload.visibility,
        owner=payload.owner,
        dept_id=payload.dept_id,
    )
    return R.success(data=kb)


@router.get("")
async def list_knowledge_bases(
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    size: int = Query(default=20, ge=1, le=200, description="每页数量"),
    keyword: Optional[str] = Query(default=None, description="按名称/描述模糊搜索"),
    dept_ids: Optional[list[str]] = Query(
        default=None,
        description="按部门过滤（可重复传参，32 位 hex；仅 data_scope=all 生效）",
    ),
    ctx: UserContext = Depends(get_user_context),
):
    """分页列出知识库（排除软删除的），可选按 keyword 过滤；部门边界按 data_scope 强制。"""
    page_result = await _service.list(
        ctx, page=page, size=size, keyword=keyword, dept_ids=dept_ids
    )
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
    """带守卫的软删除：库内仍有文档或文件夹时拒绝；通过后置 status='deleted'，
    随后不再出现在列表中。"""
    await _service.delete(kb_id)
    return R.success(msg="删除成功")
