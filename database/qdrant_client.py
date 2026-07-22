from core.source.qdrant import get_qdrant_client
from qdrant_client.models import Distance, PointStruct, VectorParams
from typing import Any, List, Optional, Sequence
from uuid import uuid4
from utils.logger import logger


class QdrantManager:
    """
    Qdrant 集合操作封装。

    负责集合初始化与向量写入 / 检索，屏蔽 qdrant-client 细节：
    - 低层接口（upsert_points）直接写入已算好的向量；
    - 高层接口（upsert_texts / search）自动调用 embedding 工厂生成向量，
      embedding 依赖延迟导入，避免仅用低层能力时引入 SDK 加载开销。
    """

    def __init__(self, collection: str) -> None:
        self.collection = collection
        self.client = get_qdrant_client()

    # ---------- 集合管理 ----------
    def ensure_collection(
        self,
        vector_size: int,
        distance: Distance = Distance.COSINE,
        recreate: bool = False,
    ) -> None:
        """
        幂等地确保集合存在。

        - recreate=True 时先删除同名集合再重建（用于维度变更 / 重置）。
        - 已存在且无需重建时直接返回，不做任何修改。
        """
        exists = self.client.collection_exists(self.collection)
        if exists and recreate:
            self.client.delete_collection(self.collection)
            logger.info(f"[Qdrant] 已删除旧集合: {self.collection}")
            exists = False

        if not exists:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=vector_size, distance=distance),
            )
            logger.info(
                f"[Qdrant] 已创建集合: {self.collection} (dim={vector_size}, distance={distance})"
            )

    def delete_collection(self) -> None:
        """删除当前集合（若存在）"""
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
            logger.info(f"[Qdrant] 已删除集合: {self.collection}")

    # ---------- 写入 ----------
    def upsert_points(
        self,
        vectors: Sequence[Sequence[float]],
        payloads: Optional[Sequence[dict]] = None,
        ids: Optional[Sequence[Any]] = None,
        ensure: bool = True,
    ) -> List[Any]:
        """
        低层写入：直接写入已算好的向量。

        - ids 缺省时自动生成 uuid4；payloads 缺省时为空字典。
        - ensure=True 时按首个向量维度自动确保集合存在。
        返回实际写入使用的 id 列表。
        """
        if not vectors:
            return []

        if ensure:
            self.ensure_collection(len(vectors[0]))

        point_ids = list(ids) if ids is not None else [uuid4().hex for _ in vectors]
        point_payloads = (
            list(payloads) if payloads is not None else [{} for _ in vectors]
        )

        points = [
            PointStruct(id=pid, vector=list(vec), payload=payload)
            for pid, vec, payload in zip(point_ids, vectors, point_payloads)
        ]
        self.client.upsert(collection_name=self.collection, points=points)
        logger.info(f"[Qdrant] 写入 {len(points)} 条向量到集合: {self.collection}")
        return point_ids

    def upsert_texts(
        self,
        texts: Sequence[str],
        payloads: Optional[Sequence[dict]] = None,
        ids: Optional[Sequence[Any]] = None,
    ) -> List[Any]:
        """
        高层写入：对文本自动生成向量并写入。

        原文默认存入 payload 的 "text" 字段，便于检索后回显。
        """
        if not texts:
            return []

        from model.embeddings.factory import get_embedding_client

        vectors = get_embedding_client().embed_documents(list(texts))

        merged_payloads: List[dict] = []
        for i, text in enumerate(texts):
            base = dict(payloads[i]) if payloads is not None else {}
            base.setdefault("text", text)
            merged_payloads.append(base)

        return self.upsert_points(vectors, payloads=merged_payloads, ids=ids)

    # ---------- 检索 ----------
    def search(
        self,
        query: str,
        top_k: int = 5,
        query_filter: Optional[Any] = None,
        with_payload: bool = True,
    ):
        """
        高层检索：对查询文本自动生成向量并做相似度检索。

        返回 qdrant-client 的 ScoredPoint 列表（含 id / score / payload）。
        """
        from model.embeddings.factory import get_embedding_client

        vector = get_embedding_client().embed_query(query)
        response = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=with_payload,
        )
        return response.points
