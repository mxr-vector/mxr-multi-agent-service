"""
LangGraph 集成示例
====================
State 里带一个 "embedding_config" 字段（用哪套配置的 name），
embed_node 按这个 name 从 bundle 里取配置、走工厂拿到 embedder、执行向量化。

实际接入 RAG/检索 pipeline 时，把 embed_node 接到你的
retrieve_node / write_to_vectorstore_node 前面即可。
"""

from __future__ import annotations
from typing import TypedDict, Optional, Literal

from langgraph.graph import StateGraph, END

from config import EmbeddingConfigBundle
from embedders import build_embedder


class EmbedState(TypedDict, total=False):
    # 输入
    config_name: str                      # 用哪套 EmbeddingConfig（对应 config.yaml 里的 name）
    mode: Literal["text", "image", "fusion"]
    texts: Optional[list[str]]
    images: Optional[list[str]]            # 路径或 URL
    pairs: Optional[list[dict]]            # fusion 模式: [{"text":..., "image":...}]
    # 输出
    vectors: Optional[list[list[float]]]
    error: Optional[str]


def make_embed_node(bundle: EmbeddingConfigBundle):
    """闭包传入配置 bundle，返回可直接注册进 StateGraph 的节点函数"""

    def embed_node(state: EmbedState) -> EmbedState:
        try:
            cfg = bundle.get(state["config_name"])
            embedder = build_embedder(cfg)  # 返回原生 langchain_core.embeddings.Embeddings

            mode = state["mode"]
            if mode == "text":
                # 原生接口：embed_documents 批量 / embed_query 单条
                vectors = embedder.embed_documents(state["texts"] or [])
            elif mode == "image":
                embed_image = getattr(embedder, "embed_image", None)
                if embed_image is None:
                    raise NotImplementedError(f"{cfg.name}（{cfg.provider}）不支持图像输入")
                vectors = embed_image(state["images"] or [])
            elif mode == "fusion":
                embed_fusion = getattr(embedder, "embed_fusion", None)
                if embed_fusion is None:
                    raise NotImplementedError(f"{cfg.name}（{cfg.provider}）不支持图文融合向量")
                vectors = embed_fusion(state["pairs"] or [])
            else:
                raise ValueError(f"未知 mode: {mode}")

            return {**state, "vectors": vectors, "error": None}
        except Exception as e:
            return {**state, "vectors": None, "error": str(e)}

    return embed_node


def build_graph(bundle: EmbeddingConfigBundle):
    graph = StateGraph(EmbedState)
    graph.add_node("embed", make_embed_node(bundle))
    graph.set_entry_point("embed")
    graph.add_edge("embed", END)
    return graph.compile()


# ---------------------------------------------------------------------------
# 使用示例
# ---------------------------------------------------------------------------
def load_bundle(config_path: str | None = None) -> EmbeddingConfigBundle:
    """
    加载配置文件，路径优先级：
      1. 显式传入的 config_path
      2. 环境变量 EMBEDDING_CONFIG_PATH
      3. 与本文件同目录下的 example_config.yaml（兜底默认值）
    """
    import os
    import yaml
    from pathlib import Path

    path = (
        config_path
        or os.getenv("EMBEDDING_CONFIG_PATH")
        or str(Path(__file__).parent / "example_config.yaml")
    )
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return EmbeddingConfigBundle(**raw)


if __name__ == "__main__":
    bundle = load_bundle()

    app = build_graph(bundle)

    # 场景1：云端纯文本向量
    result = app.invoke({
        "config_name": "text_cloud",
        "mode": "text",
        "texts": ["Flink CDC 增量同步", "Oracle 补充日志配置"],
    })
    print("text_cloud:", result.get("error") or len(result["vectors"]), "条向量")

    # 场景2：本地图文融合向量（GME）
    result = app.invoke({
        "config_name": "fusion_local",
        "mode": "fusion",
        "pairs": [{"text": "机场行李装载图", "image": "/data/sample.jpg"}],
    })
    print("fusion_local:", result.get("error") or len(result["vectors"]), "条向量")