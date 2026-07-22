from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from utils.env import ENV


@dataclass
class RerankResult:
    """
    单条重排序结果（标准化返回，屏蔽不同 SDK 差异）。

    - index:    该文档在传入 documents 中的原始下标
    - score:    query 与该文档的相关性得分（越大越相关）
    - document: 文档原文内容
    """

    index: int
    score: float
    document: str


class BaseRerankClient(ABC):
    """
    rerank 客户端统一抽象基类。

    - 每个实例在构造时从 ENV 读取 provider / 模型名 / 凭证，屏蔽不同 SDK 差异。
    - 公共方法不接收 model_name 参数，模型统一由配置决定。
    - 返回值标准化为 List[RerankResult]，按相关性得分从高到低排序。
    """

    def __init__(self) -> None:
        self.model_name: str = ENV.rerank_model_name
        self.api_key: str = ENV.rerank_api_key
        self.api_url: str = ENV.rerank_api_url

    @abstractmethod
    def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
    ) -> List[RerankResult]:
        """
        对 documents 按其与 query 的相关性重排序。

        - top_n 为 None 时返回全部文档，否则返回相关性最高的 top_n 条。
        - 返回结果按 score 从高到低排序。
        """
        ...
