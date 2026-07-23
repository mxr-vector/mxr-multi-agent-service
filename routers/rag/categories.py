import uuid
from typing import Optional

from fastapi import APIRouter, Body, Path, Query
from pydantic import BaseModel

from service.rag.categories import CategoryService
from utils.response import R

# 创建路由
router = APIRouter(prefix="/rag/categories", tags=["OpenAPI - RAG 分类管理"])

_service = CategoryService()


class CategoryCreate(BaseModel):
    """创建分类请求体。"""

    name: str
    parent_id: Optional[uuid.UUID] = None
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    """更新分类请求体（仅提供的字段会被更新，parent_id 可显式置空）。"""

    name: Optional[str] = None
    sort_order: Optional[int] = None
    parent_id: Optional[uuid.UUID] = None


@router.post("")
async def create_category(payload: CategoryCreate = Body(...)):
    """创建分类。"""
    category = await _service.create(
        name=payload.name,
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
    )
    return R.success(data=category)


@router.get("")
async def list_categories(
    parent_id: Optional[uuid.UUID] = Query(
        default=None, description="按父分类过滤，返回其直接子分类"
    ),
):
    """扁平列出分类：省略 parent_id 返回全部，传入则只返回直接子分类。"""
    categories = await _service.list(parent_id=parent_id)
    return R.success(data=categories)


@router.get("/{category_id}")
async def get_category(category_id: uuid.UUID = Path(...)):
    """按 id 获取分类。"""
    category = await _service.get(category_id)
    return R.success(data=category)


@router.put("/{category_id}")
async def update_category(
    category_id: uuid.UUID = Path(...),
    payload: CategoryUpdate = Body(...),
):
    """更新分类的 name/sort_order/parent_id。"""
    fields_set = payload.model_fields_set
    category = await _service.update(
        category_id,
        name=payload.name,
        sort_order=payload.sort_order,
        parent_id=payload.parent_id,
        parent_id_set="parent_id" in fields_set,
    )
    return R.success(data=category)


@router.delete("/{category_id}")
async def delete_category(category_id: uuid.UUID = Path(...)):
    """带守卫的物理删除：仅空分类可删除。"""
    await _service.delete(category_id)
    return R.success(msg="删除成功")
