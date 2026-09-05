from typing import List, Union

from openai import OpenAI

from model.embeddings.clients.base import BaseEmbeddingClient
from utils.env import ENV


class OpenAIEmbeddingClient(BaseEmbeddingClient):
    """
    OpenAI 兼容协议，仅支持文本向量。
    DashScope 云端 / 自建 vLLM-TEI 服务通用，仅环境变量指向的地址不同。

    使用官方 openai SDK（与 model/image/factory.py 同源），不再经 LangChain
    OpenAIEmbeddings 包装：仓库约定优先官方 SDK，provider 特性（分批、排序
    还原等）在适配器内显式完成，返回纯向量。
    """

    # 单次请求批量上限：OpenAI 兼容端点普遍限制单请求文本条数
    # （如 DashScope 兼容模式为 25 条），按批切分避免整批超限失败
    _MAX_BATCH_SIZE = 25

    def __init__(self) -> None:
        super().__init__()
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.api_url,
            # 显式超时/重试：openai SDK 默认 600s 且重试 2 次，
            # 服务不可达时会挂起十几分钟才失败，导致向量化作业表现为"卡住"
            timeout=ENV.embedding_timeout,
            max_retries=ENV.embedding_max_retries,
        )

    def embed_documents(self, docs: Union[str, List[str]]) -> List[List[float]]:
        if isinstance(docs, str):
            docs = [docs]
        vectors: List[List[float]] = []
        for start in range(0, len(docs), self._MAX_BATCH_SIZE):
            batch = docs[start : start + self._MAX_BATCH_SIZE]
            resp = self._client.embeddings.create(input=batch, model=self.model_name)
            # 按 index 还原输入顺序（协议保证 data 携带 index，防御乱序返回），
            # 保持 embed_documents 的顺序契约
            ordered = sorted(resp.data, key=lambda item: item.index)
            vectors.extend(item.embedding for item in ordered)
        return vectors

    def embed_query(self, query: str) -> List[float]:
        resp = self._client.embeddings.create(input=[query], model=self.model_name)
        return resp.data[0].embedding
