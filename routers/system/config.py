import uuid
from typing import Optional

from fastapi import APIRouter, Body, Path, Query
from pydantic import BaseModel

from service.system.config import ConfigService
from utils.response import R

# 创建路由
router = APIRouter(prefix="/system/configs", tags=["OpenAPI - 系统参数管理"])

_service = ConfigService()


class ConfigCreate(BaseModel):
    """创建参数请求体（key 全局唯一，is_builtin 创建后不可变）。"""

    name: str
    key: str
    value: Optional[str] = None
    is_builtin: bool = False
    remark: Optional[str] = None


class ConfigUpdate(BaseModel):
    """更新参数请求体（仅提供的字段会被更新，is_builtin 不可变）。"""

    name: Optional[str] = None
    key: Optional[str] = None
    value: Optional[str] = None
    remark: Optional[str] = None


@router.post("")
async def create_config(payload: ConfigCreate = Body(...)):
    """创建参数配置（key 全局唯一）。"""
    config = await _service.create(
        name=payload.name,
        key=payload.key,
        value=payload.value,
        is_builtin=payload.is_builtin,
        remark=payload.remark,
    )
    return R.success(data=config)


@router.get("")
async def list_configs(
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    size: int = Query(default=20, ge=1, le=200, description="每页数量"),
    keyword: Optional[str] = Query(default=None, description="按名称/参数键模糊搜索"),
):
    """真分页列出参数配置。"""
    page_result = await _service.list(page=page, size=size, keyword=keyword)
    return R.success(data=page_result)


@router.get("/key/{key}")
async def get_config_by_key(key: str = Path(...)):
    """按 key 精确查询参数（供业务读取配置值）。"""
    config = await _service.get_by_key(key)
    return R.success(data=config)


@router.get("/{config_id}")
async def get_config(config_id: uuid.UUID = Path(...)):
    """按 id 获取参数配置。"""
    config = await _service.get(config_id)
    return R.success(data=config)


@router.put("/{config_id}")
async def update_config(
    config_id: uuid.UUID = Path(...),
    payload: ConfigUpdate = Body(...),
):
    """更新参数配置（is_builtin 不可变，变更 key 时校验唯一）。"""
    config = await _service.update(
        config_id,
        name=payload.name,
        key=payload.key,
        value=payload.value,
        remark=payload.remark,
    )
    return R.success(data=config)


@router.delete("/{config_id}")
async def delete_config(config_id: uuid.UUID = Path(...)):
    """带守卫的物理删除：内置参数（is_builtin）拒绝删除。"""
    await _service.delete(config_id)
    return R.success(msg="删除成功")
