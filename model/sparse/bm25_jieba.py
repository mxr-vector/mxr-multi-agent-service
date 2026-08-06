"""
jieba 中文分词 BM25 稀疏向量编码器（中文词法通道）。

背景：fastembed 的 Qdrant/bm25 模型 tokenizer 面向英文（空格分词），中文文本
无空格，query 整句被哈希成单个 token，与文档侧 token 空间几乎无交集，导致
sparse 通道对中文 query 几乎零命中（混合检索实际退化为 dense 单通道）。
本编码器用 jieba 中文分词 + 词频（TF）权重替代，token 以稳定 hash 映射为
非负 int 下标；IDF 部分仍由 Qdrant 服务端（Modifier.IDF）按集合统计算。

接口与 model/sparse/bm25.py 保持一致：embed_query / embed_documents，
返回 qdrant_client.models.SparseVector。依赖 jieba（首次调用惰性加载词典）。
"""

import re
import zlib
from functools import lru_cache
from typing import List

from qdrant_client.models import SparseVector

# 检索级最小停用词集：纯虚词/标点/无区分度词（BM25 的 IDF 会再压高频词）
_STOPWORDS = frozenset(
    "的 了 是 在 和 与 或 及 等 之 也 就 都 而 被 将 从 到 于 上 下 中 里 外 "
    "有 无 为 以 对 把 让 使 用 会 能 要 可 以 这 那 该 它 他 她 们 不 没 很 "
    "更 最 并 但 却 若 如 因 果 其 各 每 某 个 种 些 时 后 前 内 间 地 得 着 "
    "过 呢 吗 吧 啊 呀 哦 嗯 什么 如何 哪些 多少 为什么 怎么 怎样 是否 可以 "
    "一个 这个 那个 ？ 。 ， 、 ： ； ！ （ ） ( ) 【 】 [ ] 《 》".split()
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


_SEG_SPLIT = re.compile(r"[\s，。？！、；：（）()【】\[\]《》\"'“”‘’…—\-:：,.;!?]+")


def _tokenize(text: str) -> List[str]:
    """jieba 分词 + 停用词过滤，保留单字/数字/字母（中文单字亦有区分度）。"""
    tokens: List[str] = []
    for segment in _SEG_SPLIT.split(text):
        if not segment:
            continue
        for word in _jieba().cut(segment):
            word = word.strip()
            if word and word not in _STOPWORDS:
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
