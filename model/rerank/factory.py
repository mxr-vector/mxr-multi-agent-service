from enum import Enum
from functools import cache
from typing import Dict, Type

from core.config_snapshot import CFG
from model.rerank.clients.base import BaseRerankClient
from model.rerank.clients.cohere import CohereRerankClient


class RerankProvider(str, Enum):
    """支持的 rerank provider 标识（rerank 模块局部概念，不属于全局配置）"""

    COHERE = "cohere"

    @classmethod
    def from_value(cls, raw: str) -> "RerankProvider":
        """解析原始配置值为枚举，非法值报清晰错误（防拼写错误）"""
        try:
            return cls(raw.strip().lower())
        except ValueError:
            valid = ", ".join(p.value for p in cls)
            raise ValueError(f"无效的 RERANK_PROVIDER: {raw!r}，合法值为: {valid}")


class RerankFactory:
    """
    rerank 策略上下文 / 工厂。

    根据配置快照 CFG.rerank.provider 自动加载对应 client，业务代码只需调用
    RerankFactory.get_client()，无需关心具体实现与 provider / 模型名。
    配置刷新时由 CFG.refresh() 清空本工厂缓存，令新配置生效。
    """

    _registry: Dict[RerankProvider, Type[BaseRerankClient]] = {
        RerankProvider.COHERE: CohereRerankClient,
    }

    @classmethod
    def get_client(cls) -> BaseRerankClient:
        provider = RerankProvider.from_value(CFG.rerank.provider or "")
        return cls._build_client(provider)

    @classmethod
    @cache
    def _build_client(cls, provider: RerankProvider) -> BaseRerankClient:
        """
        按 provider 构造并缓存 client。

        provider 与模型名由配置决定，client 无状态且可复用，因此用 functools.cache
        按 provider 缓存单例；配置刷新时由 CFG.refresh() 调用 cache_clear() 重建。
        """
        impl = cls._registry.get(provider)
        if impl is None:
            valid = ", ".join(p.value for p in cls._registry)
            raise ValueError(
                f"不支持的 rerank provider: {provider.value}，已注册: {valid}"
            )
        return impl()


get_rerank_client = RerankFactory.get_client
