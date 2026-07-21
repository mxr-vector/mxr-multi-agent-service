from typing import List, Union
from warnings import deprecated

from langchain_cohere import CohereEmbeddings

from model.embeddings.clients.base import BaseEmbeddingClient

"""
该 SDK 不兼容新版 Cohere API，暂保留但不测试，待 SDK 升级后再启用。
"""


@deprecated("SDK 不兼容新版 Cohere API，等待升级后再启用")
class CohereEmbeddingClient(BaseEmbeddingClient):
    def __init__(self) -> None:
        super().__init__()
        self._client = CohereEmbeddings(
            model=self.model_name,
            cohere_api_key=self.api_key,
            base_url=self.api_url,
        )

    def embed_documents(self, docs: Union[str, List[str]]) -> List[List[float]]:
        if isinstance(docs, str):
            docs = [docs]
        return self._client.embed_documents(docs)

    def embed_query(self, query: str) -> List[float]:
        return self._client.embed_query(query)
