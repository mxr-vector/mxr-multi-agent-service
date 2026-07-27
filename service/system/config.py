import uuid

from database.postgre_client import get_session
from database.system.config import ConfigRepository
from exception.bad_except import bad_except
from utils.page import PageResult, build_page_result


class ConfigService:
    """
    参数配置业务层。

    负责编排持久层调用与业务规则：key 全局唯一、按 key 查询、
    is_builtin 内置参数禁删保护。每个方法在共享会话中开启事务并提交。
    """

    async def create(
        self,
        name: str,
        key: str,
        value: str | None = None,
        is_builtin: bool = False,
        remark: str | None = None,
    ) -> dict:
        """创建参数配置并返回其数据；key 必须全局唯一。"""
        async with get_session() as session:
            repo = ConfigRepository(session)
            if await repo.get_by_key(key) is not None:
                bad_except(f"参数键已存在: {key}")
            config = await repo.create(
                name=name,
                key=key,
                value=value,
                is_builtin=is_builtin,
                remark=remark,
            )
            await session.commit()
            return config.to_dict()

    async def list(
        self,
        page: int = 1,
        size: int = 20,
        keyword: str | None = None,
    ) -> PageResult:
        """真分页返回参数列表（keyword 对 name/key 过滤）。"""
        async with get_session() as session:
            repo = ConfigRepository(session)
            items, total = await repo.list(page=page, size=size, keyword=keyword)
            return build_page_result([i.to_dict() for i in items], total, page, size)

    async def get(self, config_id: uuid.UUID) -> dict:
        """按 id 获取参数，不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = ConfigRepository(session)
            config = await repo.get(config_id)
            if config is None:
                bad_except(f"参数不存在: {config_id}")
            return config.to_dict()

    async def get_by_key(self, key: str) -> dict:
        """按 key 全局精确查询参数，不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = ConfigRepository(session)
            config = await repo.get_by_key(key)
            if config is None:
                bad_except(f"参数不存在: {key}")
            return config.to_dict()

    async def update(
        self,
        config_id: uuid.UUID,
        name: str | None = None,
        key: str | None = None,
        value: str | None = None,
        remark: str | None = None,
    ) -> dict:
        """
        更新参数（is_builtin 创建后不可变），不存在时抛出业务异常。
        变更 key 时校验新键全局唯一。
        """
        async with get_session() as session:
            repo = ConfigRepository(session)
            config = await repo.get(config_id)
            if config is None:
                bad_except(f"参数不存在: {config_id}")
            if key is not None and key != config.key:
                existing = await repo.get_by_key(key)
                if existing is not None:
                    bad_except(f"参数键已存在: {key}")
            config = await repo.update(
                config_id,
                name=name,
                key=key,
                value=value,
                remark=remark,
            )
            await session.commit()
            return config.to_dict()

    async def delete(self, config_id: uuid.UUID) -> None:
        """带守卫的物理删除：内置参数（is_builtin）拒绝删除。"""
        async with get_session() as session:
            repo = ConfigRepository(session)
            config = await repo.get(config_id)
            if config is None:
                bad_except(f"参数不存在: {config_id}")
            if config.is_builtin:
                bad_except("内置参数不允许删除")
            await repo.delete(config_id)
            await session.commit()
