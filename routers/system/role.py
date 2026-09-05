import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Body, Path, Query
from pydantic import BaseModel

from service.system.role import RoleService
from utils.response import R
from utils.user_context import require_admin

# 创建路由
router = APIRouter(
    prefix="/system/roles", tags=["OpenAPI - 系统角色管理"],
    dependencies=[Depends(require_admin)],
)

_service = RoleService()


class RoleCreate(BaseModel):
    """创建角色请求体（role_key 全局唯一）。"""

    name: str
    role_key: str
    data_scope: Literal["all", "dept_and_child", "dept", "self"] = "all"
    sort_order: int = 0
    status: str = "active"
    remark: Optional[str] = None


class RoleUpdate(BaseModel):
    """更新角色请求体（仅提供的字段会被更新）。"""

    name: Optional[str] = None
    role_key: Optional[str] = None
    data_scope: Optional[Literal["all", "dept_and_child", "dept", "self"]] = None
    sort_order: Optional[int] = None
    status: Optional[str] = None
    remark: Optional[str] = None


class MenuAssign(BaseModel):
    """分配菜单请求体（全量覆盖语义，传空列表即清空）。"""

    menu_ids: list[uuid.UUID]


@router.post("")
async def create_role(payload: RoleCreate = Body(...)):
    """创建角色（role_key 全局唯一）。"""
    role = await _service.create(
        name=payload.name,
        role_key=payload.role_key,
        data_scope=payload.data_scope,
        sort_order=payload.sort_order,
        status=payload.status,
        remark=payload.remark,
    )
    return R.success(data=role)


@router.get("")
async def list_roles(
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    size: int = Query(default=20, ge=1, le=200, description="每页数量"),
    keyword: Optional[str] = Query(default=None, description="按名称/角色标识模糊搜索"),
    status: Optional[str] = Query(default=None, description="按状态精确过滤"),
):
    """真分页列出角色（sort_order 升序）。"""
    page_result = await _service.list(
        page=page, size=size, keyword=keyword, status=status
    )
    return R.success(data=page_result)


@router.get("/{role_id}")
async def get_role(role_id: uuid.UUID = Path(...)):
    """按 id 获取角色。"""
    role = await _service.get(role_id)
    return R.success(data=role)


@router.put("/{role_id}")
async def update_role(
    role_id: uuid.UUID = Path(...),
    payload: RoleUpdate = Body(...),
):
    """更新角色（变更 role_key 时校验唯一）。"""
    role = await _service.update(
        role_id,
        name=payload.name,
        role_key=payload.role_key,
        data_scope=payload.data_scope,
        sort_order=payload.sort_order,
        status=payload.status,
        remark=payload.remark,
    )
    return R.success(data=role)


@router.put("/{role_id}/menus")
async def assign_menus(
    role_id: uuid.UUID = Path(...),
    payload: MenuAssign = Body(...),
):
    """分配菜单（全量覆盖：校验 menu_ids 全部存在后先清空再插入）。"""
    await _service.assign_menus(role_id, payload.menu_ids)
    return R.success(msg="分配成功")


@router.get("/{role_id}/menus")
async def list_role_menus(role_id: uuid.UUID = Path(...)):
    """查询角色已绑定的菜单 id 列表（供分配弹窗树勾选回显）。"""
    menu_ids = await _service.list_menu_ids(role_id)
    return R.success(data=menu_ids)


@router.delete("/{role_id}")
async def delete_role(role_id: uuid.UUID = Path(...)):
    """带守卫的物理删除：角色已分配给用户时拒绝删除（同事务清理菜单关联）。"""
    await _service.delete(role_id)
    return R.success(msg="删除成功")
