import uuid
from typing import Optional

from fastapi import APIRouter, Body, Path
from pydantic import BaseModel

from core.config_snapshot import CFG
from service.system.model_config import ModelConfigService
from utils.response import R

# 创建路由（模型配置卡片页专用；角色集合由代码消费方固定，不提供创建入口）
router = APIRouter(prefix="/system/model-configs", tags=["OpenAPI - 系统模型配置"])

_service = ModelConfigService()


class ModelConfigUpdate(BaseModel):
    """更新模型配置请求体（role/is_builtin 不可变；api_key 留空或为掩码占位则不修改）。"""

    name: Optional[str] = None
    model_name: Optional[str] = None
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    provider: Optional[str] = None
    timeout: Optional[int] = None
    max_retries: Optional[int] = None
    context_window: Optional[int] = None
    extra: Optional[dict] = None
    remark: Optional[str] = None


@router.get("")
async def list_model_configs():
    """全量列出模型配置（api_key 掩码），供卡片页渲染。"""
    configs = await _service.list()
    return R.success(data=configs)


@router.get("/role/{role}")
async def get_model_config_by_role(role: str = Path(...)):
    """按角色查询单个模型配置（api_key 掩码）。"""
    config = await _service.get_by_role(role)
    return R.success(data=config)


@router.put("/{config_id}")
async def update_model_config(
    config_id: uuid.UUID = Path(...),
    payload: ModelConfigUpdate = Body(...),
):
    """
    原子更新单行模型配置；成功后触发配置快照刷新（免重启生效）。
    刷新失败不影响本次保存（保留旧快照），结果经 data.refreshed 透出供前端提示。
    """
    config = await _service.update(
        config_id,
        name=payload.name,
        model_name=payload.model_name,
        api_url=payload.api_url,
        api_key=payload.api_key,
        provider=payload.provider,
        timeout=payload.timeout,
        max_retries=payload.max_retries,
        context_window=payload.context_window,
        extra=payload.extra,
        remark=payload.remark,
    )
    refreshed = await CFG.refresh()
    config["refreshed"] = refreshed
    msg = (
        "保存成功，配置已热更新"
        if refreshed
        else "保存成功，但配置热更新校验未通过，仍沿用旧配置"
    )
    return R.success(data=config, msg=msg)


@router.delete("/{config_id}")
async def delete_model_config(config_id: uuid.UUID = Path(...)):
    """带守卫的物理删除：内置模型配置（is_builtin）拒绝删除。"""
    await _service.delete(config_id)
    # 删除后刷新配置快照；结果经 data.refreshed 透出供前端提示
    refreshed = await CFG.refresh()
    return R.success(data={"refreshed": refreshed}, msg="删除成功")
