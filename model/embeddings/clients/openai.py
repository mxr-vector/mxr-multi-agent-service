from typing import List, Union

from langchain_openai import OpenAIEmbeddings

from model.embeddings.clients.base import BaseEmbeddingClient


class OpenAIEmbeddingClient(BaseEmbeddingClient):
    """
    OpenAI 兼容协议，仅支持文本向量。
    DashScope 云端 / 自建 vLLM-TEI 服务通用，仅环境变量指向的地址不同。
    """

    def __init__(self) -> None:
        super().__init__()
        self._client = OpenAIEmbeddings(
            model=self.model_name,
            api_key=self.api_key,
            base_url=self.api_url,
        )

    def embed_documents(self, docs: Union[str, List[str]]) -> List[List[float]]:
        if isinstance(docs, str):
            docs = [docs]
        return self._client.embed_documents(docs)

    def embed_query(self, query: str) -> List[float]:
        return self._client.embed_query(query)
