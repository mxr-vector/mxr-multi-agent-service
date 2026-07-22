from typing import List, Union
from warnings import deprecated

import cohere

from model.embeddings.clients.base import BaseEmbeddingClient

"""
cohere SDK v2. langchain_cohere 不兼容新版，因此使用官方SDK.    
"""

# cohere 内部默认向量维度（不暴露为 env 配置）
_DEFAULT_DIMENSION = 1024
class CohereEmbeddingClient(BaseEmbeddingClient):
    def __init__(self) -> None:
        super().__init__()
        self._client = cohere.ClientV2(
            api_key=self.api_key,
            base_url=self.api_url,
        )

    def embed_documents(self, docs: Union[str, List[str]]) -> List[List[float]]:
        if isinstance(docs, str):
            docs = [docs]
        return self._client.embed(
            texts=docs,
            model=self.model_name,
            input_type="search_document",
            output_dimension=_DEFAULT_DIMENSION,
            embedding_types=["float"],
        )

    def embed_query(self, query: str) -> List[float]:
        return self._client.embed(
            texts=query,
            model=self.model_name,
            input_type="search_query",
            output_dimension=_DEFAULT_DIMENSION,
            embedding_types=["float"],
        )
