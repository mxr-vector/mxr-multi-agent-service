"""
BM25 稀疏向量编码器（jieba 中文 + 英文词法编码，主路径）。

背景：fastembed 的 Qdrant/bm25 模型 tokenizer 面向英文（空格分词），中文文本
无空格，query 整句被哈希成单个 token，与文档侧 token 空间几乎无交集，导致
sparse 通道对中文 query 几乎零命中（混合检索实际退化为 dense 单通道）。
评测（test/dataset01，1000 条分层抽样）验证 jieba 中文 BM25 使严格 Recall@10
0.798 → 0.865、宽松 Recall@10 0.888 → 0.930。

本编码器对中英双语统一支持：中文连续块走 jieba 分词，英文/数字块按空格与
标点切词并统一小写（消除大小写导致的 token 错位），中英混合文本自动分流；
以词频（TF）权重产出稀疏向量，token 以稳定 hash 映射为非负 int 下标；
IDF 部分仍由 Qdrant 服务端（Modifier.IDF）按集合统计算。
接口保持 embed_query / embed_documents（返回 qdrant_client.models.SparseVector），
调用方（upsert_hybrid / hybrid_search / agent 检索）零改动。

旧 fastembed 实现保留为 legacy_* 函数，仅供迁移回滚与对照使用（勿在生产主路径调用）。
"""

import re
import zlib
from functools import lru_cache
from typing import List

from qdrant_client.models import SparseVector

from utils.env import ENV

# 检索级最小停用词集：纯虚词/标点/无区分度词（BM25 的 IDF 会再压高频词）
_STOPWORDS = frozenset(
    "的 了 是 在 和 与 或 及 等 之 也 就 都 而 被 将 从 到 于 上 下 中 里 外 "
    "有 无 为 以 对 把 让 使 用 会 能 要 可 以 这 那 该 它 他 她 们 不 没 很 "
    "更 最 并 但 却 若 如 因 果 其 各 每 某 个 种 些 时 后 前 内 间 地 得 着 "
    "过 呢 吗 吧 啊 呀 哦 嗯 什么 如何 哪些 多少 为什么 怎么 怎样 是否 可以 "
    "一个 这个 那个 ？ 。 ， 、 ： ； ！ （ ） ( ) 【 】 [ ] 《 》".split()
)

# 英文高频虚词（轻量集合；BM25 的 IDF 会再压高频词）
_EN_STOPWORDS = frozenset(
    "a an the and or but of in on at to for with by from as is are was were "
    "be been being it its this that these those i you he she we they them his "
    "her their our your do does did done have has had not no nor so if then "
    "than while what which who whom when where why how all any each every few "
    "more most other some such only own same too very can will just should "
    "could would may might must about into over after before under again once "
    "here there".split()
)

# 词 → 稳定非负 int 下标（crc32 截断；集合 token 规模数万，碰撞概率可忽略）
_HASH_MASK = 0x7FFFFFFF


def _hash_token(token: str) -> int:
    return zlib.crc32(token.encode("utf-8")) & _HASH_MASK


@lru_cache(maxsize=1)
def _jieba():
    """惰性加载 jieba（首次调用初始化词典），进程内复用。"""
    import jieba

    jieba.initialize()
    return jieba


# 分隔符切段（不含 ' 与 -：连字符/撇号词保留给 _MIX_BLOCK，如 O'Brien、state-of-the-art）
_SEG_SPLIT = re.compile(r"[\s，。？！、；：（）()【】\[\]《》\"“”‘’…—:：,.;!?]+")

# 中英混合文本分流：连续中文块 | 英文/数字块（含连字符/撇号，如 O'Brien）
_MIX_BLOCK = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+(?:['\-][a-zA-Z0-9]+)*")

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _tokenize(text: str) -> List[str]:
    """中英双语分词：中文连续块走 jieba，英文/数字块切词统一小写。

    英文统一小写以消除大小写 token 错位（Football vs football）；
    中英紧邻文本（如"使用Python开发"）由 _MIX_BLOCK 自动分流。
    """
    tokens: List[str] = []
    for segment in _SEG_SPLIT.split(text):
        if not segment:
            continue
        for block in _MIX_BLOCK.findall(segment):
            if _CJK_RE.search(block):
                for word in _jieba().cut(block):
                    word = word.strip()
                    if word and word not in _STOPWORDS:
                        tokens.append(word)
            else:
                word = block.lower()
                if word not in _EN_STOPWORDS:
                    tokens.append(word)
    return tokens


def _to_sparse(tokens: List[str]) -> SparseVector:
    """词频（TF）权重；同 hash 的词合并计数。空词集返回空稀疏向量。"""
    counts: dict[int, float] = {}
    for token in tokens:
        h = _hash_token(token)
        counts[h] = counts.get(h, 0.0) + 1.0
    if not counts:
        return SparseVector(indices=[], values=[])
    indices = sorted(counts)
    return SparseVector(indices=indices, values=[counts[i] for i in indices])


def embed_documents(texts: List[str]) -> List[SparseVector]:
    """对一批文档编码为 jieba BM25 稀疏向量（输入顺序保持一致）。"""
    if not texts:
        return []
    return [_to_sparse(_tokenize(text)) for text in texts]


def embed_query(text: str) -> SparseVector:
    """对查询文本编码为 jieba BM25 稀疏向量。"""
    return _to_sparse(_tokenize(text))


# ============================================================================
# 以下为 legacy 实现（fastembed Qdrant/bm25，英文分词器，中文失效）。
# 保留仅供迁移回滚（utils/migrate_sparse.py --encoder legacy）与对照评测使用，
# 生产主路径勿调用。
# ============================================================================

# fastembed 支持的 BM25 词法稀疏模型标识
BM25_MODEL_NAME = "Qdrant/bm25"


@lru_cache(maxsize=1)
def _get_legacy_model():
    """惰性加载并缓存 fastembed BM25 编码器（legacy，仅供回滚）。"""
    from fastembed import SparseTextEmbedding

    ENV.bm25_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = str(ENV.bm25_cache_dir)
    try:
        return SparseTextEmbedding(
            model_name=BM25_MODEL_NAME, cache_dir=cache_dir, local_files_only=True
        )
    except Exception:
        return SparseTextEmbedding(model_name=BM25_MODEL_NAME, cache_dir=cache_dir)


def _legacy_to_sparse(embedding) -> SparseVector:
    """把 fastembed SparseEmbedding 转成 qdrant SparseVector。"""
    return SparseVector(
        indices=embedding.indices.tolist(),
        values=embedding.values.tolist(),
    )


def legacy_embed_documents(texts: List[str]) -> List[SparseVector]:
    """legacy：fastembed BM25 批量编码（英文分词器，中文 query 失效）。"""
    if not texts:
        return []
    model = _get_legacy_model()
    return [_legacy_to_sparse(emb) for emb in model.embed(list(texts))]


def legacy_embed_query(text: str) -> SparseVector:
    """legacy：fastembed BM25 查询编码（英文分词器，中文 query 失效）。"""
    model = _get_legacy_model()
    embedding = next(iter(model.query_embed(text)))
    return _legacy_to_sparse(embedding)
