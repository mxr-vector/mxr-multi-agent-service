from typing import List, Optional

import cohere

from model.rerank.clients.base import BaseRerankClient, RerankResult

"""
cohere SDK v2。langchain_cohere 不兼容新版，因此使用官方 SDK cohere。
本地 vLLM 兼容 cohere rerank 接口，但对其做了简化，因此需要适当修改。
"""


class CohereRerankClient(BaseRerankClient):
    """
    Cohere 兼容协议重排序客户端。

    - 每个实例持有自身的 api_key / api_url，通过 ClientV2 下发，不做全局修改。
    - 对外仅暴露标准接口 rerank，返回按相关性排序的 List[RerankResult]。
    """

    def __init__(self) -> None:
        super().__init__()
        self._client = cohere.ClientV2(
            api_key=self.api_key,
            base_url=self.api_url,
        )

    def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
    ) -> List[RerankResult]:
        if not documents:
            return []

        resp = self._client.rerank(
            model=self.model_name,
            query=query,
            documents=documents,
            top_n=top_n if top_n is not None else len(documents),
        )
        # SDK 已按相关性从高到低返回，result.index 指向原始 documents 下标
        return [
            RerankResult(
                index=result.index,
                score=result.relevance_score,
                document=documents[result.index],
            )
            for result in resp.results
        ]
