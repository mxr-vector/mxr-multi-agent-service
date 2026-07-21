from http import HTTPStatus
from typing import Any, Dict, List, Union

import dashscope

from model.embeddings.clients.base import BaseEmbeddingClient

# DashScope 内部默认向量维度（不暴露为 env 配置）
_DEFAULT_DIMENSION = 1024


class DashScopeEmbeddingClient(BaseEmbeddingClient):
    """
    DashScope 向量客户端。

    - 每个实例持有自身的 api_key / api_url，通过每次调用传参下发，
      不再全局修改 dashscope.api_key / base_http_api_url。
    - 对外仅暴露标准接口：embed_documents / embed_query 返回纯向量；
      text_type 的映射在适配器内部完成，调用方无感知。
    - 返回向量按 text_index 排序，保证与输入顺序一致。
    """

    def __init__(self) -> None:
        super().__init__()
        self._client = dashscope
        self._dimension = _DEFAULT_DIMENSION

    def embed_documents(self, docs: Union[str, List[str]]) -> List[List[float]]:
        if isinstance(docs, str):
            docs = [docs]
        output = self._call_text_embedding(docs, text_type="document")
        return self._to_vectors(output)

    def embed_query(self, query: str) -> List[float]:
        output = self._call_text_embedding([query], text_type="query")
        return self._to_vectors(output)[0]

    def embed_multimodal(
        self,
        input: List[Dict[str, str]],
        isfusion: bool = False,
        text_type: str = "document",
    ) -> Any:
        """
        多模态向量。输入可以是视频或图片：
        video = "https://.../new+video.mp4"; input = [{'video': video}]
        image = "https://.../256_1.png";    input = [{'image': image}]
        """
        resp = self._client.MultiModalEmbedding.call(
            model=self.model_name,
            input=input,
            dimension=self._dimension,
            enable_fusion=isfusion,
            text_type=text_type,
            api_key=self.api_key,
            base_address=self.api_url,
        )
        if resp.status_code != HTTPStatus.OK:
            raise RuntimeError(
                f"DashScope 多模态向量请求失败: {resp.code} {resp.message}"
            )
        return resp.output

    def _call_text_embedding(
        self, input: List[str], text_type: str
    ) -> Dict[str, Any]:
        resp = self._client.TextEmbedding.call(
            model=self.model_name,
            input=input,
            dimension=self._dimension,
            text_type=text_type,
            api_key=self.api_key,
            base_address=self.api_url,
        )
        if resp.status_code != HTTPStatus.OK:
            raise RuntimeError(
                f"DashScope 向量请求失败: {resp.code} {resp.message}"
            )
        return resp.output

    @staticmethod
    def _to_vectors(output: Dict[str, Any]) -> List[List[float]]:
        """从 SDK 输出中提取纯向量，并按 text_index 还原输入顺序"""
        embeddings = output["embeddings"]
        ordered = sorted(embeddings, key=lambda item: item.get("text_index", 0))
        return [item["embedding"] for item in ordered]
