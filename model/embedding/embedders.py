"""
Embedder 实现层（LangChain 原生接口版）
========================================
所有 embedder 都实现 langchain_core.embeddings.Embeddings：
    embed_documents(texts: list[str]) -> list[list[float]]
    embed_query(text: str) -> list[float]

这样可以直接塞进 Chroma / FAISS 等 vectorstore 的 embedding_function 参数，
和 LangChain / LangGraph 生态无缝对接。

多模态独立向量 / 融合向量在 embed_documents/embed_query 之外，
额外挂 embed_image / embed_fusion 方法（不在 Embeddings 基类里，但不影响兼容性，
纯文本场景的代码完全不用关心这两个方法存不存在）。

云端优先走 OpenAI 兼容协议（OpenAIEmbeddings + base_url），
本地自建的 HTTP 服务（vLLM / TEI 起的 OpenAI 兼容 embedding 服务）也复用同一个类，
只是 base_url 换成内网地址、api_key 随便填一个占位值即可——云端和本地HTTP服务
本质上是同一套调用逻辑，不需要分开写两个类。
"""

from __future__ import annotations
import os

from langchain_core.embeddings import Embeddings

from config import EmbeddingConfig


# ---------------------------------------------------------------------------
# 文本信息向量 · 本地（Qwen3-Embedding 等，HuggingFace 原生，直接用不用包装）
# ---------------------------------------------------------------------------
def _build_hf_text(cfg: EmbeddingConfig) -> Embeddings:
    from langchain_huggingface import HuggingFaceEmbeddings
    import torch

    device = cfg.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"

    return HuggingFaceEmbeddings(
        model_name=cfg.model_name,
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": cfg.normalize},
    )


# ---------------------------------------------------------------------------
# 文本信息向量 · OpenAI 兼容协议（云端 DashScope / 自建 vLLM-TEI / 真OpenAI 通用）
# 区分「云端」还是「本地HTTP服务」只看 base_url 填的是外网地址还是内网地址，
# 代码逻辑完全一样，所以云端和本地HTTP服务共用这一个 provider。
# ---------------------------------------------------------------------------
def _build_openai_compatible_text(cfg: EmbeddingConfig) -> Embeddings:
    from langchain_openai import OpenAIEmbeddings

    api_key = os.getenv(cfg.api_key_env) if cfg.api_key_env else "not-needed"
    return OpenAIEmbeddings(
        api_key=api_key,
        base_url=cfg.base_url,             # 云端填DashScope地址，本地HTTP服务填内网地址
        model=cfg.model_name,
        check_embedding_ctx_length=False,  # 非OpenAI官方服务必须关掉，否则报InvalidParameter
    )


# ---------------------------------------------------------------------------
# 多模态独立向量 · 本地（OpenCLIP，langchain_experimental 原生，自带 embed_image）
# ---------------------------------------------------------------------------
def _build_open_clip_local(cfg: EmbeddingConfig) -> Embeddings:
    from langchain_experimental.open_clip import OpenCLIPEmbeddings

    checkpoint = cfg.extra.get("checkpoint", "laion2b_s32b_b79k")
    return OpenCLIPEmbeddings(model_name=cfg.model_name, checkpoint=checkpoint)


# ---------------------------------------------------------------------------
# 多模态独立向量 · 云端（DashScope multimodal-embedding-v1）
# 没有 OpenAI 兼容协议可用，只能用 dashscope SDK 自己包一层
# ---------------------------------------------------------------------------
class DashScopeMultimodalEmbeddings(Embeddings):
    def __init__(self, cfg: EmbeddingConfig):
        import dashscope
        self.cfg = cfg
        self._dashscope = dashscope
        self._dashscope.api_key = os.getenv(cfg.api_key_env or "DASHSCOPE_API_KEY")
        if cfg.base_url:
            self._dashscope.base_http_api_url = cfg.base_url

    def _call(self, inputs: list[dict]) -> list[list[float]]:
        resp = self._dashscope.MultiModalEmbedding.call(
            model=self.cfg.model_name, input=inputs
        )
        if resp.status_code != 200:
            raise RuntimeError(f"DashScope multimodal embedding 调用失败: {resp.message}")
        return [item["embedding"] for item in resp.output["embeddings"]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._call([{"text": t} for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._call([{"text": text}])[0]

    def embed_image(self, image_paths_or_urls: list[str]) -> list[list[float]]:
        return self._call([{"image": img} for img in image_paths_or_urls])


# ---------------------------------------------------------------------------
# 多模态融合向量 · 本地（GME-Qwen2-VL，没有现成LangChain封装，自己包一层）
# ---------------------------------------------------------------------------
class GMEFusionEmbeddings(Embeddings):
    def __init__(self, cfg: EmbeddingConfig):
        from transformers import AutoModel
        self.cfg = cfg
        self._model = AutoModel.from_pretrained(
            cfg.model_name,
            torch_dtype="float16",
            device_map=cfg.device,
            trust_remote_code=True,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._model.get_text_embeddings(texts=texts).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self._model.get_text_embeddings(texts=[text]).tolist()[0]

    def embed_image(self, image_paths_or_urls: list[str]) -> list[list[float]]:
        return self._model.get_image_embeddings(images=image_paths_or_urls).tolist()

    def embed_fusion(self, pairs: list[dict]) -> list[list[float]]:
        """pairs: [{"text": ..., "image": ...}, ...] -> 每对生成一个融合向量"""
        texts = [p.get("text", "") for p in pairs]
        images = [p.get("image") for p in pairs]
        return self._model.get_fused_embeddings(texts=texts, images=images).tolist()


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------
_BUILDERS = {
    "hf_text": _build_hf_text,
    "openai_compatible_text": _build_openai_compatible_text,
    "open_clip_local": _build_open_clip_local,
    "dashscope_multimodal": lambda cfg: DashScopeMultimodalEmbeddings(cfg),
    "gme_local": lambda cfg: GMEFusionEmbeddings(cfg),
}

_INSTANCE_CACHE: dict[str, Embeddings] = {}


def build_embedder(cfg: EmbeddingConfig) -> Embeddings:
    if cfg.name in _INSTANCE_CACHE:
        return _INSTANCE_CACHE[cfg.name]

    builder = _BUILDERS.get(cfg.provider)
    if builder is None:
        raise ValueError(f"未知的 provider '{cfg.provider}'，可选: {list(_BUILDERS.keys())}")

    instance = builder(cfg)
    _INSTANCE_CACHE[cfg.name] = instance
    return instance