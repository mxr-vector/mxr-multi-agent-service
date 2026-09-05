import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Body, Path, Query
from pydantic import BaseModel

from service.system.dept import DeptService
from utils.response import R
from utils.user_context import require_admin

# 创建路由
router = APIRouter(
    prefix="/system/depts", tags=["OpenAPI - 系统部门管理"],
    dependencies=[Depends(require_admin)],
)

_service = DeptService()


class DeptCreate(BaseModel):
    """创建部门请求体（parent_id 为空表示顶级部门）。"""

    name: str
    parent_id: Optional[uuid.UUID] = None
    sort_order: int = 0
    leader: Optional[str] = None
    status: str = "active"


class DeptUpdate(BaseModel):
    """更新部门请求体（仅提供的字段会被更新，parent_id 可显式置空升为顶级）。"""

    name: Optional[str] = None
    sort_order: Optional[int] = None
    leader: Optional[str] = None
    status: Optional[str] = None
    parent_id: Optional[uuid.UUID] = None


@router.post("")
async def create_dept(payload: DeptCreate = Body(...)):
    """创建部门（父部门须存在）。"""
    dept = await _service.create(
        name=payload.name,
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
        leader=payload.leader,
        status=payload.status,
    )
    return R.success(data=dept)


@router.get("")
async def list_depts(
    keyword: Optional[str] = Query(default=None, description="按部门名称模糊搜索"),
    status: Optional[str] = Query(default=None, description="按状态精确过滤"),
):
    """扁平列出全部部门（sort_order 升序），树由前端组装。"""
    depts = await _service.list(keyword=keyword, status=status)
    return R.success(data=depts)


@router.get("/{dept_id}")
async def get_dept(dept_id: uuid.UUID = Path(...)):
    """按 id 获取部门。"""
    dept = await _service.get(dept_id)
    return R.success(data=dept)


@router.put("/{dept_id}")
async def update_dept(
    dept_id: uuid.UUID = Path(...),
    payload: DeptUpdate = Body(...),
):
    """更新部门；变更 parent_id 时校验存在性与防环（非自身/后代）。"""
    fields_set = payload.model_fields_set
    dept = await _service.update(
        dept_id,
        name=payload.name,
        sort_order=payload.sort_order,
        leader=payload.leader,
        status=payload.status,
        parent_id=payload.parent_id,
        parent_id_set="parent_id" in fields_set,
    )
    return R.success(data=dept)


@router.delete("/{dept_id}")
async def delete_dept(dept_id: uuid.UUID = Path(...)):
    """带守卫的物理删除：存在子部门或关联用户时拒绝删除。"""
    await _service.delete(dept_id)
    return R.success(msg="删除成功")
