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
    - 混合集合为命名向量（dense + sparse），写入与检索均走混合通道；
    - embedding / BM25 依赖延迟导入，避免仅做集合管理时引入 SDK 加载开销。
    """

    def __init__(self, collection: str) -> None:
        self.collection = collection
        self.client = get_qdrant_client()

    # ---------- 集合管理 ----------
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
        已存在且无需重建时直接返回，不做任何修改。
        """
        exists = self.client.collection_exists(self.collection)
        if exists and recreate:
            self.client.delete_collection(self.collection)
            logger.info(f"[Qdrant] 已删除旧集合: {self.collection}")
            exists = False

        if exists:
            # 命名向量时 params.vectors 是 dict，匿名稠密时是 VectorParams；
            # 集合已存在但为匿名稠密 schema 时，命名向量写入必然失败
            # （历史 footgun：ensure 建普通集合后此处因已存在而跳过创建），
            # 提前告警暴露 schema 冲突而非在 upsert 时报错
            vectors = getattr(
                self.client.get_collection(self.collection).config.params,
                "vectors",
                None,
            )
            if not isinstance(vectors, dict):
                logger.warning(
                    f"[Qdrant] 集合 {self.collection} 已存在但为匿名稠密向量 schema，"
                    "与混合写入（upsert_hybrid 命名向量 dense+sparse）不匹配，"
                    "后续混合写入可能失败，请重建集合"
                )
            return
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
    def hybrid_search(
        self,
        query: str,
        limit: int = 5,
        prefetch_limit: Optional[int] = None,
        with_payload: bool = True,
        dense_vector=None,
        sparse_vector=None,
    ):
        """
        高层混合检索：一次 Query API 调用同时发起 dense 与 sparse 预取，
        由服务端 RRF 融合排序，并按 point id 去重后返回。

        - dense 向量由 embedding 工厂生成，sparse 向量由 BM25 词法编码器生成；
          两者均可由调用方预先算好传入（如多集合扇出复用同一查询向量），
          缺省时在本方法内按 query 生成；
        - prefetch_limit 控制单通道召回广度，缺省取 limit*4（上限 clamp 100）；
        - limit 为融合后保留的候选上限。
        返回去重后的 ScoredPoint 列表（含 id / score / payload）。
        """
        if dense_vector is None:
            from model.embeddings.factory import get_embedding_client

            dense_vector = get_embedding_client().embed_query(query)
        if sparse_vector is None:
            from model.sparse.bm25 import embed_query as sparse_embed_query

            sparse_vector = sparse_embed_query(query)
        if prefetch_limit is None:
            # 缺省取 limit*4 并 clamp 到 100：RRF 融合前单通道召回宽度应显著
            # 大于最终保留数（缺省与 limit 相等会压低两路候选交集，融合退化为
            # 通道内排序拼接）；上限 100 防止过大的 prefetch 值被 Qdrant 拒绝
            prefetch_limit = min(limit * 4, 100)

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
