from typing import List, Union
import cohere
from model.embeddings.clients.base import BaseEmbeddingClient
from utils.env import ENV

"""
cohere SDK v2. langchain_cohere 不兼容新版，因此使用官方SDK cohere.  
# input_type="search_document",
# output_dimension=_DEFAULT_DIMENSION,
本地vllm兼容cohere，但对其做了简化，因此需要适当修改
"""

# cohere 内部默认向量维度（不暴露为 env 配置）
_DEFAULT_DIMENSION = 1024
class CohereEmbeddingClient(BaseEmbeddingClient):
    def __init__(self) -> None:
        super().__init__()
        self._client = cohere.ClientV2(
            api_key=self.api_key,
            base_url=self.api_url,
            # 显式超时/重试：SDK 默认 timeout=300s 且重试多次，
            # 服务不可达时会挂起数分钟才失败，导致向量化作业表现为"卡住"
            timeout=ENV.embedding_timeout,
            max_retries=ENV.embedding_max_retries,
        )

    def embed_documents(self, docs: Union[str, List[str]]) -> List[List[float]]:
        if isinstance(docs, str):
            docs = [docs]
        resp = self._client.embed(
            texts=docs,
            model=self.model_name,
            input_type="document",
            # input_type="search_document",
            # output_dimension=_DEFAULT_DIMENSION,
            embedding_types=["float"],
        )
        return resp.embeddings.float_

    def embed_query(self, query: Union[str, List[str]]) -> List[float]:
        if isinstance(query, str):
            query = [query]
        resp =  self._client.embed(
            texts=query,
            model=self.model_name,
            input_type="query",
            # input_type="search_query",
            # output_dimension=_DEFAULT_DIMENSION,
            embedding_types=["float"],
        )
        return resp.embeddings.float_[0]
