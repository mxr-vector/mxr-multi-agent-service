import uuid

from database.postgre_client import get_session
from database.system.model_config import ModelConfigRepository
from exception.bad_except import bad_except

# 掩码占位标记：前端未修改密钥时回传的展示值含此串，服务层据此判定“不更新 api_key”
API_KEY_MASK = "****"


def mask_api_key(raw: str | None) -> str:
    """对 api_key 脱敏：长度 ≥ 12 保留前 4 后 4、中间以 **** 替代；否则全掩码。"""
    if not raw:
        return ""
    if len(raw) >= 12:
        return f"{raw[:4]}{API_KEY_MASK}{raw[-4:]}"
    return API_KEY_MASK


def _to_masked_dict(config) -> dict:
    """ORM 转字典并对 api_key 脱敏（对外响应统一走此出口）。"""
    data = config.to_dict()
    data["api_key"] = mask_api_key(data.get("api_key"))
    return data


class ModelConfigService:
    """
    模型配置业务层。

    负责编排持久层调用与业务规则：查询返回掩码 api_key、更新时 role/is_builtin
    不可变、api_key 缺省或掩码占位不覆盖、内置行禁删。每个方法在共享会话中
    开启事务并提交。配置快照刷新由路由层在写操作成功后触发（本层保持纯粹）。
    """

    async def list(self) -> list[dict]:
        """全量返回模型配置（api_key 掩码，按 role 升序）。"""
        async with get_session() as session:
            repo = ModelConfigRepository(session)
            items = await repo.list()
            return [_to_masked_dict(item) for item in items]

    async def get_by_role(self, role: str) -> dict:
        """按 role 查询模型配置（api_key 掩码），不存在时抛业务异常。"""
        async with get_session() as session:
            repo = ModelConfigRepository(session)
            config = await repo.get_by_role(role)
            if config is None:
                bad_except(f"模型配置不存在: {role}")
            return _to_masked_dict(config)

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
    ) -> dict:
        """
        原子更新单行模型配置（单行 UPDATE）：role/is_builtin 不可变；
        api_key 为空或为掩码占位（含 ****）时保持原值不变；不存在时抛业务异常。
        """
        # 掩码占位或空 → 视为“不修改密钥”，避免把掩码值写回覆盖真实密钥
        if not api_key or API_KEY_MASK in api_key:
            api_key = None
        async with get_session() as session:
            repo = ModelConfigRepository(session)
            config = await repo.get(config_id)
            if config is None:
                bad_except(f"模型配置不存在: {config_id}")
            config = await repo.update(
                config_id,
                name=name,
                model_name=model_name,
                api_url=api_url,
                api_key=api_key,
                provider=provider,
                timeout=timeout,
                max_retries=max_retries,
                extra=extra,
                remark=remark,
            )
            await session.commit()
            return _to_masked_dict(config)

    async def delete(self, config_id: uuid.UUID) -> None:
        """带守卫的物理删除：内置行（is_builtin）拒绝删除。"""
        async with get_session() as session:
            repo = ModelConfigRepository(session)
            config = await repo.get(config_id)
            if config is None:
                bad_except(f"模型配置不存在: {config_id}")
            if config.is_builtin:
                bad_except("内置模型配置不允许删除")
            await repo.delete(config_id)
            await session.commit()
