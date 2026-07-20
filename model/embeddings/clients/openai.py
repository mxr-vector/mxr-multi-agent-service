from utils.env import ENV
from langchain_openai import OpenAIEmbeddings
from functools import lru_cache
from typing import Union, List, Optional


class OpenAIClientCfg:

    @staticmethod
    @lru_cache(maxsize=8)
    def get_client(
        model_name: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> OpenAIEmbeddings:
        """
        OpenAI兼容协议，仅支持文本向量。
        DashScope云端 / 自建vLLM-TEI服务通用，同一个类只是环境变量指向不同地址。
        """
        return OpenAIEmbeddings(
            model=model_name,
            api_key=api_key or ENV.embedding_api_key,
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


OpenAIClient = OpenAIClientCfg()
