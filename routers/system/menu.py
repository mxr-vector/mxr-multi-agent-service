import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Body, Path, Query
from pydantic import BaseModel

from service.system.menu import MenuService
from utils.response import R
from utils.user_context import require_admin

# 创建路由
router = APIRouter(
    prefix="/system/menus", tags=["OpenAPI - 系统菜单管理"],
    dependencies=[Depends(require_admin)],
)

_service = MenuService()


class MenuCreate(BaseModel):
    """创建菜单请求体（menu_type 取 dir/menu/button，创建后不可变）。"""

    menu_type: str
    label: str
    parent_id: Optional[uuid.UUID] = None
    name: Optional[str] = None
    path: Optional[str] = None
    component: Optional[str] = None
    icon: Optional[str] = None
    perms: Optional[str] = None
    visible: bool = True
    sort_order: int = 0
    status: str = "active"


class MenuUpdate(BaseModel):
    """更新菜单请求体（仅提供的字段会被更新，parent_id 可显式置空升为顶级）。"""

    label: Optional[str] = None
    name: Optional[str] = None
    path: Optional[str] = None
    component: Optional[str] = None
    icon: Optional[str] = None
    perms: Optional[str] = None
    visible: Optional[bool] = None
    sort_order: Optional[int] = None
    status: Optional[str] = None
    parent_id: Optional[uuid.UUID] = None


@router.post("")
async def create_menu(payload: MenuCreate = Body(...)):
    """创建菜单（menu_type 枚举校验、父节点须存在）。"""
    menu = await _service.create(
        menu_type=payload.menu_type,
        label=payload.label,
        parent_id=payload.parent_id,
        name=payload.name,
        path=payload.path,
        component=payload.component,
        icon=payload.icon,
        perms=payload.perms,
        visible=payload.visible,
        sort_order=payload.sort_order,
        status=payload.status,
    )
    return R.success(data=menu)


@router.get("")
async def list_menus(
    keyword: Optional[str] = Query(default=None, description="按菜单名称模糊搜索"),
    status: Optional[str] = Query(default=None, description="按状态精确过滤"),
):
    """扁平列出全部菜单（sort_order 升序），树由前端组装。"""
    menus = await _service.list(keyword=keyword, status=status)
    return R.success(data=menus)


@router.get("/{menu_id}")
async def get_menu(menu_id: uuid.UUID = Path(...)):
    """按 id 获取菜单。"""
    menu = await _service.get(menu_id)
    return R.success(data=menu)


@router.put("/{menu_id}")
async def update_menu(
    menu_id: uuid.UUID = Path(...),
    payload: MenuUpdate = Body(...),
):
    """更新菜单（menu_type 不可变；变更 parent_id 时校验存在性与防环）。"""
    fields_set = payload.model_fields_set
    menu = await _service.update(
        menu_id,
        label=payload.label,
        name=payload.name,
        path=payload.path,
        component=payload.component,
        icon=payload.icon,
        perms=payload.perms,
        visible=payload.visible,
        sort_order=payload.sort_order,
        status=payload.status,
        parent_id=payload.parent_id,
        parent_id_set="parent_id" in fields_set,
    )
    return R.success(data=menu)


@router.delete("/{menu_id}")
async def delete_menu(menu_id: uuid.UUID = Path(...)):
    """带守卫的物理删除：存在子菜单或仍被角色绑定时拒绝删除。"""
    await _service.delete(menu_id)
    return R.success(msg="删除成功")
