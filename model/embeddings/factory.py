from functools import cache
from typing import Dict, Type

from utils.env import ENV
from model.embeddings.clients.base import BaseEmbeddingClient
from model.embeddings.clients.openai import OpenAIEmbeddingClient
from model.embeddings.clients.dashscope import DashScopeEmbeddingClient
from model.embeddings.clients.cohere import CohereEmbeddingClient


class EmbeddingFactory:
    """
    embedding 策略上下文 / 工厂。

    根据 ENV.embedding_provider 自动加载对应 client，业务代码只需调用
    EmbeddingFactory.get_client()，无需关心具体实现与 provider / 模型名。
    """

    # provider 字符串 -> client 类的注册表，新增 provider 只需在此登记一行
    _registry: Dict[str, Type[BaseEmbeddingClient]] = {
        "openai": OpenAIEmbeddingClient,
        "dashscope": DashScopeEmbeddingClient,
        # Cohere 已 deprecated（SDK 不兼容新版 API），保留注册以便 SDK 升级后启用
        "cohere": CohereEmbeddingClient,
    }

    @classmethod
    def get_client(cls) -> BaseEmbeddingClient:
        provider = ENV.embedding_provider.strip().lower()
        return cls._build_client(provider)

    @classmethod
    @cache
    def _build_client(cls, provider: str) -> BaseEmbeddingClient:
        """
        按 provider 构造并缓存 client。

        provider 与模型名由配置决定、进程内固定不变，client 无状态且可复用，
        因此用 functools.cache 按 provider 缓存单例，避免每次重复构造与重复读取 ENV。
        """
        impl = cls._registry.get(provider)
        if impl is None:
            valid = ", ".join(cls._registry)
            raise ValueError(
                f"无效的 EMBEDDING_PROVIDER: {provider!r}，合法值为: {valid}"
            )
        return impl()


get_embedding_client = EmbeddingFactory.get_client
