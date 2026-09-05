import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Body, Path, Query
from pydantic import BaseModel

from service.system.config import ConfigService
from core.config_snapshot import CFG, scalar_value_type
from utils.response import R
from utils.user_context import require_admin

# 创建路由
router = APIRouter(
    prefix="/system/configs", tags=["OpenAPI - 系统参数管理"],
    dependencies=[Depends(require_admin)],
)

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
    # 参数变更后刷新配置快照（白名单标量参数免重启生效；刷新结果不影响本次写入）；结果经 data.refreshed 透出供前端提示
    refreshed = await CFG.refresh()
    config["refreshed"] = refreshed
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


@router.get("/scalars")
async def list_scalar_configs():
    """返回全部内置运行参数（is_builtin=true，created_at 升序），供模型配置页运行参数区域渲染。

    展示范围由 is_builtin 标记驱动（新增内置参数自动入表）；每行附 value_type
    （int/url/text）供前端数据驱动校验，前端不再镜像白名单键；SCALAR_KEYS
    白名单退为 CFG 快照的内部消费契约（见 design D7）。
    """
    configs = await _service.list_builtin()
    for c in configs:
        c["value_type"] = scalar_value_type(c["key"])
    return R.success(data=configs)


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
    """更新参数配置（is_builtin 不可变，内置参数 key 不可改名，变更 key 时校验唯一）。"""
    config = await _service.update(
        config_id,
        name=payload.name,
        key=payload.key,
        value=payload.value,
        remark=payload.remark,
    )
    # 参数变更后刷新配置快照（白名单标量参数免重启生效）；结果经 data.refreshed 透出供前端提示
    refreshed = await CFG.refresh()
    config["refreshed"] = refreshed
    return R.success(data=config)


@router.delete("/{config_id}")
async def delete_config(config_id: uuid.UUID = Path(...)):
    """带守卫的物理删除：内置参数（is_builtin）拒绝删除。"""
    await _service.delete(config_id)
    # 参数删除后刷新配置快照；结果经 data.refreshed 透出供前端提示
    refreshed = await CFG.refresh()
    return R.success(data={"refreshed": refreshed}, msg="删除成功")
