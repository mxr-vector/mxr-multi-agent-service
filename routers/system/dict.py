import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Body, Path, Query
from pydantic import BaseModel

from agent.constants.enums.system import RecordStatus
from service.system.dict import DictDataService, DictTypeService
from utils.response import R
from utils.user_context import get_user_context, require_admin

# 创建路由（dict-types 与 dict-data 两组端点共用一个模块级 router）
# 读接口开放给全体已登录用户（供前端全局词典与下拉框消费）；写与删除接口施加 require_admin 校验
router = APIRouter(
    prefix="/system", tags=["OpenAPI - 系统字典管理"],
    dependencies=[Depends(get_user_context)],
)

_type_service = DictTypeService()
_data_service = DictDataService()


class DictTypeCreate(BaseModel):
    """创建字典类型请求体（type 键全局唯一）。"""

    name: str
    type: str
    status: str = RecordStatus.ACTIVE
    remark: Optional[str] = None


class DictTypeUpdate(BaseModel):
    """更新字典类型请求体（仅提供的字段会被更新，改 type 键会级联更新字典数据）。"""

    name: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    remark: Optional[str] = None


class DictDataCreate(BaseModel):
    """创建字典数据请求体（dict_type 必须指向已存在的类型键）。"""

    dict_type: str
    label: str
    value: str
    sort_order: int = 0
    is_default: bool = False
    status: str = RecordStatus.ACTIVE
    remark: Optional[str] = None


class DictDataUpdate(BaseModel):
    """更新字典数据请求体（仅提供的字段会被更新，dict_type 创建后不可变）。"""

    label: Optional[str] = None
    value: Optional[str] = None
    sort_order: Optional[int] = None
    is_default: Optional[bool] = None
    status: Optional[str] = None
    remark: Optional[str] = None


# ---------- 字典类型 ----------


@router.post("/dict-types", dependencies=[Depends(require_admin)])
async def create_dict_type(payload: DictTypeCreate = Body(...)):
    """创建字典类型（type 键全局唯一，需要管理员权限）。"""
    dict_type = await _type_service.create(
        name=payload.name,
        type=payload.type,
        status=payload.status,
        remark=payload.remark,
    )
    return R.success(data=dict_type)


@router.get("/dict-types")
async def list_dict_types(
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    size: int = Query(default=20, ge=1, le=200, description="每页数量"),
    keyword: Optional[str] = Query(default=None, description="按名称/类型键模糊搜索"),
    status: Optional[str] = Query(default=None, description="按状态精确过滤"),
):
    """真分页列出字典类型。"""
    page_result = await _type_service.list(
        page=page, size=size, keyword=keyword, status=status
    )
    return R.success(data=page_result)


@router.get("/dict-types/{dict_type_id}")
async def get_dict_type(dict_type_id: uuid.UUID = Path(...)):
    """按 id 获取字典类型。"""
    dict_type = await _type_service.get(dict_type_id)
    return R.success(data=dict_type)


@router.put("/dict-types/{dict_type_id}", dependencies=[Depends(require_admin)])
async def update_dict_type(
    dict_type_id: uuid.UUID = Path(...),
    payload: DictTypeUpdate = Body(...),
):
    """更新字典类型；变更 type 键时同事务级联更新其下字典数据（需要管理员权限）。"""
    dict_type = await _type_service.update(
        dict_type_id,
        name=payload.name,
        type=payload.type,
        status=payload.status,
        remark=payload.remark,
    )
    return R.success(data=dict_type)


@router.delete("/dict-types/{dict_type_id}", dependencies=[Depends(require_admin)])
async def delete_dict_type(dict_type_id: uuid.UUID = Path(...)):
    """带守卫的物理删除：类型下仍有字典数据时拒绝删除（需要管理员权限）。"""
    await _type_service.delete(dict_type_id)
    return R.success(msg="删除成功")


# ---------- 字典数据 ----------


@router.post("/dict-data", dependencies=[Depends(require_admin)])
async def create_dict_data(payload: DictDataCreate = Body(...)):
    """创建字典数据（dict_type 必须已存在，需要管理员权限）。"""
    dict_data = await _data_service.create(
        dict_type=payload.dict_type,
        label=payload.label,
        value=payload.value,
        sort_order=payload.sort_order,
        is_default=payload.is_default,
        status=payload.status,
        remark=payload.remark,
    )
    return R.success(data=dict_data)


@router.get("/dict-data")
async def list_dict_data(
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    size: int = Query(default=20, ge=1, le=200, description="每页数量"),
    dict_type: Optional[str] = Query(default=None, description="按类型键精确过滤"),
    keyword: Optional[str] = Query(default=None, description="按标签模糊搜索"),
    status: Optional[str] = Query(default=None, description="按状态精确过滤"),
):
    """真分页列出字典数据（sort_order 升序）。"""
    page_result = await _data_service.list(
        page=page, size=size, dict_type=dict_type, keyword=keyword, status=status
    )
    return R.success(data=page_result)


@router.get("/dict-data/all")
async def get_all_dict_data_map(
    status: Optional[str] = Query(default=RecordStatus.ACTIVE, description="按状态精确过滤，缺省仅返回启用项"),
):
    """按字典类型分组聚合返回全部字典项（{ [dict_type]: items[] }），供前端全局词典一次性加载。"""
    data = await _data_service.get_all_map(status=status or "")
    return R.success(data=data)


@router.get("/dict-data/type/{dict_type}")
async def list_dict_data_by_type(
    dict_type: str = Path(...),
    status: Optional[str] = Query(default=None, description="按状态精确过滤"),
):
    """按类型键取全量字典项（sort_order 升序），供前端下拉框消费。"""
    items = await _data_service.list_by_type(dict_type, status=status or "")
    return R.success(data=items)


@router.get("/dict-data/{dict_data_id}")
async def get_dict_data(dict_data_id: uuid.UUID = Path(...)):
    """按 id 获取字典数据。"""
    dict_data = await _data_service.get(dict_data_id)
    return R.success(data=dict_data)


@router.put("/dict-data/{dict_data_id}", dependencies=[Depends(require_admin)])
async def update_dict_data(
    dict_data_id: uuid.UUID = Path(...),
    payload: DictDataUpdate = Body(...),
):
    """更新字典数据（dict_type 创建后不可变，需要管理员权限）。"""
    dict_data = await _data_service.update(
        dict_data_id,
        label=payload.label,
        value=payload.value,
        sort_order=payload.sort_order,
        is_default=payload.is_default,
        status=payload.status,
        remark=payload.remark,
    )
    return R.success(data=dict_data)


@router.delete("/dict-data/{dict_data_id}", dependencies=[Depends(require_admin)])
async def delete_dict_data(dict_data_id: uuid.UUID = Path(...)):
    """物理删除字典数据（需要管理员权限）。"""
    await _data_service.delete(dict_data_id)
    return R.success(msg="删除成功")
