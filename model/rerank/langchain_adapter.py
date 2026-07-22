from typing import Optional, Sequence

from langchain_core.callbacks import Callbacks
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from pydantic import PrivateAttr

from model.rerank.factory import get_rerank_client


class LangChainRerankAdapter(BaseDocumentCompressor):
    """
    将统一封装的 BaseRerankClient 适配为 LangChain 的 BaseDocumentCompressor 类型。

    - 业务/LangGraph 侧只需拿到一个标准 BaseDocumentCompressor 实例，
      即可传入 ContextualCompressionRetriever 等作为压缩/重排序器。
    - 底层仍走 RerankFactory，provider / 模型名差异继续由 factory + 各 client 屏蔽。
    - 依据 query 对文档重排序，取相关性最高的 top_n 条，并把得分写回 metadata。
    """

    top_n: Optional[int] = None
    """保留的文档条数；None 表示保留全部（仅重排序不裁剪）"""

    score_key: str = "relevance_score"
    """相关性得分写入 Document.metadata 的键名"""

    _client = PrivateAttr()

    def model_post_init(self, __context) -> None:
        self._client = get_rerank_client()

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        if not documents:
            return []

        docs = list(documents)
        results = self._client.rerank(
            query=query,
            documents=[doc.page_content for doc in docs],
            top_n=self.top_n,
        )

        compressed = []
        for result in results:
            doc = docs[result.index]
            doc.metadata[self.score_key] = result.score
            compressed.append(doc)
        return compressed


def get_langchain_reranker(top_n: Optional[int] = None) -> BaseDocumentCompressor:
    """供 LangChain 体系（ContextualCompressionRetriever 等）使用的标准重排序器实例。"""
    return LangChainRerankAdapter(top_n=top_n)


