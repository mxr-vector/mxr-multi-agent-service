import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from entity.system.model_config import ModelConfig


class ModelConfigRepository:
    """
    模型配置持久层（DAO）。

    只负责纯粹的数据访问，不含业务规则（api_key 掩码、role 不可变、
    is_builtin 禁删守卫放 service 层）。共用 `database/postgre_client.py`
    的会话，事务提交由 service 层控制。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> list[ModelConfig]:
        """全量列出模型配置（按 role 升序，供卡片页与配置快照加载）。"""
        stmt = select(ModelConfig).order_by(ModelConfig.role)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, config_id: uuid.UUID) -> ModelConfig | None:
        """按 id 获取单条模型配置，不存在返回 None。"""
        return await self.session.get(ModelConfig, config_id)

    async def get_by_role(self, role: str) -> ModelConfig | None:
        """按 role 全局精确查询，不存在返回 None（供按角色读取与配置快照加载）。"""
        stmt = select(ModelConfig).where(ModelConfig.role == role)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(
        self,
        config_id: uuid.UUID,
        name: str | None = None,
        model_name: str | None = None,
        api_url: str | None = None,
        api_key: str | None = None,
        provider: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        extra: dict | None = None,
        remark: str | None = None,
    ) -> ModelConfig | None:
        """
        更新模型配置字段（role/is_builtin 创建后不可变），显式刷新 updated_at；
        不存在返回 None。api_key 为 None 时视为不修改（掩码占位判定在 service 层）。
        """
        config = await self.session.get(ModelConfig, config_id)
        if config is None:
            return None
        if name is not None:
            config.name = name
        if model_name is not None:
            config.model_name = model_name
        if api_url is not None:
            config.api_url = api_url
        if api_key is not None:
            config.api_key = api_key
        if provider is not None:
            config.provider = provider
        if timeout is not None:
            config.timeout = timeout
        if max_retries is not None:
            config.max_retries = max_retries
        if extra is not None:
            config.extra = extra
        if remark is not None:
            config.remark = remark
        config.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return config

    async def delete(self, config_id: uuid.UUID) -> None:
        """物理删除模型配置行（is_builtin 禁删守卫在 service 层完成）。"""
        await self.session.execute(
            delete(ModelConfig).where(ModelConfig.id == config_id)
        )
