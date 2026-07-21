from abc import ABC, abstractmethod
from typing import List, Union

from utils.env import ENV


class BaseEmbeddingClient(ABC):
    """
    embedding 客户端统一抽象基类。

    - 每个实例在构造时从 ENV 读取 provider / 模型名 / 凭证，屏蔽不同 SDK 差异。
    - 公共方法不接收 model_name 参数，模型统一由配置决定。
    - 返回值标准化为纯向量：
        embed_documents -> List[List[float]]
        embed_query     -> List[float]
    - 特异化能力（如多模态向量）默认抛 NotImplementedError，
      仅支持该能力的具体 client 重写。
    """

    def __init__(self) -> None:
        self.model_name: str = ENV.embedding_model_name
        self.api_key: str = ENV.embedding_api_key
        self.api_url: str = ENV.embedding_api_url

    @abstractmethod
    def embed_documents(self, docs: Union[str, List[str]]) -> List[List[float]]:
        """批量文档向量，返回顺序与输入一致"""
        ...

    @abstractmethod
    def embed_query(self, query: str) -> List[float]:
        """单条查询向量"""
        ...

    def embed_multimodal(self, *args, **kwargs) -> List[List[float]]:
        """多模态向量（默认不支持，由具体 client 按需重写）"""
        raise NotImplementedError(f"{self.__class__.__name__} 暂不支持多模态向量")
