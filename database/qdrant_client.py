from core.source.qdrant import get_qdrant_client
from qdrant_client import models
from qdrant_client.models import Distance, PointStruct, VectorParams
from typing import Any, List, Optional, Sequence
from uuid import UUID, uuid4
from utils.logger import logger

# 混合检索命名向量：dense 走语义（COSINE），sparse 走 BM25 关键词（IDF 由服务端计算）
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"

# 知识库 collection 命名规则：由知识库 id 后端派生，前端无感知。
# 形如 kb_{id.hex}_v1（id 去连字符的 32 位十六进制，版本段固定 v1）。
KB_COLLECTION_PREFIX = "kb_"
KB_COLLECTION_VERSION = "v1"


def build_kb_collection_name(kb_id: UUID) -> str:
    """由知识库 UUID 派生 Qdrant collection 名称：kb_{id.hex}_v1。

    id 使用 .hex 去除连字符以贴合 Qdrant 命名习惯；版本段固定为 v1。
    这是全局唯一的命名入口，业务层不得再拼接或接受外部传入的 collection 名。
    """
    return f"{KB_COLLECTION_PREFIX}{kb_id.hex}_{KB_COLLECTION_VERSION}"


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

    def ensure_hybrid_collection(
        self,
        dense_size: int,
        distance: Distance = Distance.COSINE,
        recreate: bool = False,
    ) -> None:
        """
        幂等地确保混合检索集合存在（命名向量：dense + sparse）。

        - dense：语义稠密向量，按 dense_size 维、指定 distance 创建；
        - sparse：BM25 关键词稀疏向量，以 Modifier.IDF 创建，IDF 由服务端计算；
        - recreate=True 时先删除同名集合再重建（用于 schema 变更 / 重置）。
        已存在且无需重建时直接返回。
        """
        exists = self.client.collection_exists(self.collection)
        if exists and recreate:
            self.client.delete_collection(self.collection)
            logger.info(f"[Qdrant] 已删除旧集合: {self.collection}")
            exists = False

        if not exists:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config={
                    DENSE_VECTOR_NAME: VectorParams(size=dense_size, distance=distance),
                },
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: models.SparseVectorParams(
                        modifier=models.Modifier.IDF,
                    ),
                },
            )
            logger.info(
                f"[Qdrant] 已创建混合集合: {self.collection} "
                f"(dense_dim={dense_size}, distance={distance}, sparse=BM25/IDF)"
            )

    def delete_collection(self) -> None:
        """删除当前集合（若存在）"""
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
            logger.info(f"[Qdrant] 已删除集合: {self.collection}")

    def delete_points(self, ids: Sequence[Any]) -> None:
        """按 point id 列表删除点（集合不存在或 ids 为空时直接返回）。

        用于灰度重建：新版本点写入后，清理旧版本遗留的向量点。
        """
        point_ids = list(ids)
        if not point_ids or not self.client.collection_exists(self.collection):
            return
        self.client.delete(
            collection_name=self.collection,
            points_selector=models.PointIdsList(points=point_ids),
        )
        logger.info(f"[Qdrant] 已删除 {len(point_ids)} 个点 (集合: {self.collection})")

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

    def upsert_hybrid(
        self,
        texts: Sequence[str],
        payloads: Optional[Sequence[dict]] = None,
        ids: Optional[Sequence[Any]] = None,
        recreate: bool = False,
    ) -> List[Any]:
        """
        高层写入（混合）：对文本同时生成 dense + sparse 向量并以命名向量写入。

        - dense 由 embedding 工厂生成，sparse 由 BM25 词法编码器生成；
        - 按首个 dense 向量维度确保混合集合存在（recreate 时重建 schema）；
        - 原文默认存入 payload["text"]，便于检索后回显。
        返回实际写入的 point id 列表。
        """
        if not texts:
            return []

        from model.embeddings.factory import get_embedding_client
        from model.sparse.bm25 import embed_documents as sparse_embed_documents

        text_list = list(texts)
        dense_vectors = get_embedding_client().embed_documents(text_list)
        sparse_vectors = sparse_embed_documents(text_list)

        self.ensure_hybrid_collection(len(dense_vectors[0]), recreate=recreate)

        point_ids = list(ids) if ids is not None else [uuid4().hex for _ in text_list]
        points = []
        for i, text in enumerate(text_list):
            base = dict(payloads[i]) if payloads is not None else {}
            base.setdefault("text", text)
            points.append(
                PointStruct(
                    id=point_ids[i],
                    vector={
                        DENSE_VECTOR_NAME: list(dense_vectors[i]),
                        SPARSE_VECTOR_NAME: sparse_vectors[i],
                    },
                    payload=base,
                )
            )

        self.client.upsert(collection_name=self.collection, points=points)
        logger.info(f"[Qdrant] 写入 {len(points)} 条混合向量到集合: {self.collection}")
        return point_ids

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

    def hybrid_search(
        self,
        query: str,
        limit: int = 5,
        prefetch_limit: Optional[int] = None,
        with_payload: bool = True,
    ):
        """
        高层混合检索：一次 Query API 调用同时发起 dense 与 sparse 预取，
        由服务端 RRF 融合排序，并按 point id 去重后返回。

        - dense 向量由 embedding 工厂生成，sparse 向量由 BM25 词法编码器生成；
        - prefetch_limit 控制单通道召回广度，缺省与 limit 一致；
        - limit 为融合后保留的候选上限。
        返回去重后的 ScoredPoint 列表（含 id / score / payload）。
        """
        from model.embeddings.factory import get_embedding_client
        from model.sparse.bm25 import embed_query as sparse_embed_query

        dense_vector = get_embedding_client().embed_query(query)
        sparse_vector = sparse_embed_query(query)
        prefetch_limit = prefetch_limit if prefetch_limit is not None else limit

        response = self.client.query_points(
            collection_name=self.collection,
            prefetch=[
                models.Prefetch(
                    query=dense_vector,
                    using=DENSE_VECTOR_NAME,
                    limit=prefetch_limit,
                ),
                models.Prefetch(
                    query=sparse_vector,
                    using=SPARSE_VECTOR_NAME,
                    limit=prefetch_limit,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=with_payload,
        )
        return self._dedup_by_id(response.points)

    @staticmethod
    def _dedup_by_id(points):
        """按 point id 去重，保留首次出现（即融合后排名最靠前）的候选。

        同一分片可能同时被 dense 与 sparse 通道召回，去重后只出现一次。
        """
        seen = set()
        unique = []
        for point in points:
            if point.id in seen:
                continue
            seen.add(point.id)
            unique.append(point)
        return unique
