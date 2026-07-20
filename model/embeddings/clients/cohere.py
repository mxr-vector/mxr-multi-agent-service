from warnings import deprecated
from utils.env import ENV
from langchain_cohere import CohereEmbeddings
from functools import lru_cache
from typing import Union, List, Optional

"""
该SDK不兼容新版Cohere API
"""


@deprecated
class CohereClientCfg:
    @staticmethod
    @lru_cache(maxsize=8)
    def get_client(
        model_name: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> CohereEmbeddings:
        return CohereEmbeddings(
            model=model_name,
            cohere_api_key=api_key or ENV.embedding_api_key,
            base_url=base_url or ENV.embedding_api_url,
        )

    @classmethod
    def embed_documents(
        cls,
        model_name: str,
        docs: Union[str, list[str]],
    ) -> List[List[float]]:
        """
        批量文档向量
        """

        client = cls.get_client(model_name)

        if isinstance(docs, str):
            docs = [docs]
        return client.embed_documents(docs)

    @classmethod
    def embed_query(
        cls,
        model_name: str,
        query: str,
    ) -> List[float]:
        """
        查询向量
        """

        client = cls.get_client(model_name)

        return client.embed_query(query)


CohereClient = CohereClientCfg()
