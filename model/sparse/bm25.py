"""
BM25 稀疏向量编码器（CPU 词法编码，非神经模型）。

用于混合检索的稀疏（关键词）通路：在摄取与查询时把文本编码为 BM25 稀疏向量。
本编码器只做分词与词频统计，不加载神经权重、不依赖 GPU，因此与
"神经推理统一放在 HTTP 模型服务后面" 的项目原则不冲突。

IDF 部分交由 Qdrant 服务端处理：集合的 sparse 向量以 Modifier.IDF 创建，
本编码器只产出词项频次权重（indices/values），Qdrant 查询时套用 IDF。

依赖 fastembed（由 qdrant-client[fastembed] extra 引入）的 Qdrant/bm25 模型。
模型按 provider 固定、进程内复用，因此以 lru_cache 缓存单例，首次调用时惰性加载。
"""

from functools import lru_cache
from typing import List

from qdrant_client.models import SparseVector

from utils.env import ENV

# fastembed 支持的 BM25 词法稀疏模型标识
BM25_MODEL_NAME = "Qdrant/bm25"


@lru_cache(maxsize=1)
def _get_model():
    """惰性加载并缓存 BM25 编码器（首次调用时构造，避免导入即加载）。

    优先以 local_files_only 从本地缓存加载（不发任何 HF 网络请求），
    缓存缺失时才回退到联网下载；避免 HF 镜像不可达时拖死向量化作业。
    """
    from fastembed import SparseTextEmbedding

    # 缓存目录由 BM25_CACHE_DIR 配置（默认项目内 model/hf，避免 %TEMP% 被系统清理）
    ENV.bm25_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = str(ENV.bm25_cache_dir)

    try:
        return SparseTextEmbedding(
            model_name=BM25_MODEL_NAME, cache_dir=cache_dir, local_files_only=True
        )
    except Exception:
        # 本地无缓存（首次部署）：联网下载，需要 HF_ENDPOINT 可达
        return SparseTextEmbedding(model_name=BM25_MODEL_NAME, cache_dir=cache_dir)


def _to_sparse_vector(embedding) -> SparseVector:
    """把 fastembed SparseEmbedding 转成 qdrant SparseVector。"""
    return SparseVector(
        indices=embedding.indices.tolist(),
        values=embedding.values.tolist(),
    )


def embed_documents(texts: List[str]) -> List[SparseVector]:
    """对一批文档编码为 BM25 稀疏向量（输入顺序保持一致）。"""
    if not texts:
        return []
    model = _get_model()
    return [_to_sparse_vector(emb) for emb in model.embed(list(texts))]


def embed_query(text: str) -> SparseVector:
    """对查询文本编码为 BM25 稀疏向量。"""
    model = _get_model()
    embedding = next(iter(model.query_embed(text)))
    return _to_sparse_vector(embedding)
