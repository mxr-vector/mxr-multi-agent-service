from typing import List
from warnings import deprecated

from langchain_core.embeddings import Embeddings

from model.embeddings.factory import get_embedding_client


@deprecated("业务侧优先使用官方 SDK 客户端；本适配器仅为 LangChain 生态桥接保留")
class LangChainEmbeddingAdapter(Embeddings):
    """
    将统一封装的 BaseEmbeddingClient 适配为 LangChain 的 Embeddings 类型。

    - 业务/LangGraph 侧只需拿到一个标准 langchain_core.embeddings.Embeddings 实例，
      即可传入 PGVector、各类 VectorStore / Retriever，通过其类型校验。
    - 底层仍走 EmbeddingFactory，provider / 模型名差异继续由 factory + 各 client 屏蔽。
    - 方法签名与 LangChain 契约一致；异步方法沿用基类默认实现（线程池执行同步方法）。
    """

    def __init__(self) -> None:
        self._client = get_embedding_client()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._client.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._client.embed_query(text)


def get_langchain_embeddings() -> Embeddings:
    """供 LangChain 体系（PGVector / Retriever 等）使用的标准 Embeddings 实例。"""
    return LangChainEmbeddingAdapter()
