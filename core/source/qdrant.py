from dataclasses import dataclass
from functools import cached_property, lru_cache
from qdrant_client import QdrantClient
from utils.env import ENV

@dataclass(frozen=True)
class QdrantConfig:
    """
    Qdrant 向量数据库配置
    """

    host: str
    port: int
    api_key: str
    https: bool = False

    @cached_property
    def url(self) -> str:
        """
        Qdrant HTTP(REST) 服务地址；协议由 https 开关决定
        """
        scheme = "https" if self.https else "http"
        return f"{scheme}://{self.host}:{self.port}"

    @classmethod
    def from_env(cls):
        return cls(
            host=ENV.qdrant_host,
            port=ENV.qdrant_port,
            api_key=ENV.qdrant_api_key,
            https=ENV.qdrant_https,
        )


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    """
    获取进程级唯一的 Qdrant 客户端单例。

    配置由 ENV 决定、进程内固定不变，客户端可复用，
    因此用 lru_cache 缓存单例，避免重复建连与重复读取 ENV。
    业务代码统一通过本函数获取客户端，勿直接实例化 QdrantClient。
    """
    config = QdrantConfig.from_env()
    return QdrantClient(url=config.url, api_key=config.api_key)
