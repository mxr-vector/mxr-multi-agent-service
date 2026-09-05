import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel

from service.rag.folder import FolderService
from utils.response import R
from utils.user_context import UserContext, get_user_context

# 创建路由
router = APIRouter(prefix="/rag/folders", tags=["OpenAPI - RAG 文件夹管理"])

_service = FolderService()


class FolderCreate(BaseModel):
    """创建文件夹请求体（knowledge_base_id 必填，创建后不可变）。"""

    name: str
    knowledge_base_id: uuid.UUID
    parent_id: Optional[uuid.UUID] = None
    sort_order: int = 0


class FolderUpdate(BaseModel):
    """更新文件夹请求体（仅提供的字段会被更新，parent_id 可显式置空）。"""

    name: Optional[str] = None
    sort_order: Optional[int] = None
    parent_id: Optional[uuid.UUID] = None


@router.post("")
async def create_folder(
    payload: FolderCreate = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """创建文件夹（归属指定知识库，须对当前用户可见；dept_id 从上下文注入）。"""
    folder = await _service.create(
        ctx,
        name=payload.name,
        knowledge_base_id=payload.knowledge_base_id,
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
    )
    return R.success(data=folder)


@router.get("")
async def list_folders(
    knowledge_base_id: uuid.UUID = Query(..., description="所属知识库 id，必填"),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    size: int = Query(default=20, ge=1, le=200, description="每页数量"),
    parent_id: Optional[uuid.UUID] = Query(
        default=None, description="按父文件夹过滤，返回其直接子文件夹"
    ),
    keyword: Optional[str] = Query(default=None, description="按文件夹名称模糊搜索"),
    ctx: UserContext = Depends(get_user_context),
):
    """分页扁平列出某知识库内的文件夹：省略 parent_id 返回全部，传入则只返回直接子文件夹；可选 keyword 过滤。"""
    page_result = await _service.list(
        ctx,
        knowledge_base_id=knowledge_base_id,
        page=page,
        size=size,
        parent_id=parent_id,
        keyword=keyword,
    )
    return R.success(data=page_result)


@router.get("/{folder_id}")
async def get_folder(folder_id: uuid.UUID = Path(...)):
    """按 id 获取文件夹。"""
    folder = await _service.get(ctx, folder_id)
    return R.success(data=folder)


@router.put("/{folder_id}")
async def update_folder(
    folder_id: uuid.UUID = Path(...),
    payload: FolderUpdate = Body(...),
    ctx: UserContext = Depends(get_user_context),
):
    """更新文件夹的 name/sort_order/parent_id（knowledge_base_id 不可变）。"""
    fields_set = payload.model_fields_set
    folder = await _service.update(
        ctx,
        folder_id,
        name=payload.name,
        sort_order=payload.sort_order,
        parent_id=payload.parent_id,
        parent_id_set="parent_id" in fields_set,
    )
    return R.success(data=folder)


@router.delete("/{folder_id}")
async def delete_folder(
    folder_id: uuid.UUID = Path(...),
    ctx: UserContext = Depends(get_user_context),
):
    """带守卫的物理删除：仅空文件夹（无子文件夹、无文档）可删除。"""
    await _service.delete(ctx, folder_id)
    return R.success(msg="删除成功")
