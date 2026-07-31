from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from entity.system.config import Config
from utils.page import paginate


class ConfigRepository:
    """
    参数配置持久层（DAO）。

    只负责纯粹的数据访问，不含业务规则（key 唯一校验、is_builtin 禁删
    保护放 service 层）。共用 `database/postgre_client.py` 的会话，
    事务提交由 service 层控制。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        name: str,
        key: str,
        value: str | None = None,
        is_builtin: bool = False,
        remark: str | None = None,
    ) -> Config:
        """插入一条参数配置，id 由数据库 uuidv7() 生成。"""
        config = Config(
            name=name,
            key=key,
            value=value,
            is_builtin=is_builtin,
            remark=remark,
        )
        self.session.add(config)
        await self.session.flush()
        return config

    async def list(
        self,
        page: int = 1,
        size: int = 20,
        keyword: str | None = None,
    ) -> tuple[list[Config], int]:
        """
        真分页列表：服务端过滤（keyword 对 name/key 做 ILIKE），
        total 为过滤后的总数。返回 (items, total)。
        """
        stmt = select(Config)
        if keyword:
            pattern = f"%{keyword}%"
            stmt = stmt.where(Config.name.ilike(pattern) | Config.key.ilike(pattern))
        stmt = stmt.order_by(Config.created_at.desc())
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def list_by_keys(self, keys: list[str]) -> list[Config]:
        """按 key 集合批量精确查询（供模型配置页运行参数区域一次性读取）。"""
        stmt = select(Config).where(Config.key.in_(keys))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, config_id: uuid.UUID) -> Config | None:
        """按 id 获取单条参数，不存在返回 None。"""
        return await self.session.get(Config, config_id)

    async def get_by_key(self, key: str) -> Config | None:
        """按 key 全局精确查询，不存在返回 None（供唯一性校验与按 key 读取）。"""
        stmt = select(Config).where(Config.key == key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(
        self,
        config_id: uuid.UUID,
        name: str | None = None,
        key: str | None = None,
        value: str | None = None,
        remark: str | None = None,
    ) -> Config | None:
        """更新参数字段（is_builtin 创建后不可变），并显式刷新 updated_at；不存在返回 None。"""
        config = await self.session.get(Config, config_id)
        if config is None:
            return None
        if name is not None:
            config.name = name
        if key is not None:
            config.key = key
        if value is not None:
            config.value = value
        if remark is not None:
            config.remark = remark
        config.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return config

    async def delete(self, config_id: uuid.UUID) -> None:
        """物理删除参数行（is_builtin 禁删守卫在 service 层完成）。"""
        await self.session.execute(delete(Config).where(Config.id == config_id))
