"""
向量模型配置 Schema
====================
按两个维度组合出具体的 embedder：

维度一 VectorType（向量类型）
    TEXT                    文本信息向量           只吃文本，输出单一向量空间
    MULTIMODAL_INDEPENDENT  多模态独立向量          文本/图像分别编码，但落在同一向量空间（可跨模态检索），
                             例如 CLIP、DashScope multimodal-embedding-v1
    MULTIMODAL_FUSION       多模态融合向量          文本+图像联合编码成一个向量（图文对本身就是一条向量），
                             例如 GME-Qwen2-VL

维度二 SourceType（来源）
    LOCAL   本地加载（HuggingFace / ModelScope 权重，走 GPU/CPU 推理）
    CLOUD   云端 API（DashScope 等，走 HTTP 调用）

provider 字段决定具体走哪个实现类，在 embedders.py 的 REGISTRY 里注册。
"""

from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field


class VectorType(str, Enum):
    TEXT = "text"
    MULTIMODAL_INDEPENDENT = "multimodal_independent"
    MULTIMODAL_FUSION = "multimodal_fusion"


class SourceType(str, Enum):
    LOCAL = "local"
    CLOUD = "cloud"


class EmbeddingConfig(BaseModel):
    name: str = Field(..., description="配置的唯一标识，graph 节点里按这个名字取用")
    vector_type: VectorType
    source: SourceType
    provider: str = Field(
        ..., description="具体实现，如 dashscope_text / dashscope_multimodal / "
                          "hf_text / clip_local / gme_local"
    )
    model_name: str
    api_key_env: Optional[str] = Field(
        None, description="云端调用时，从哪个环境变量读取 API Key"
    )
    base_url: Optional[str] = None
    device: str = "cpu"          # 本地模型用：cpu / cuda / cuda:0
    dimension: Optional[int] = None
    normalize: bool = True
    batch_size: int = 8
    extra: dict[str, Any] = Field(default_factory=dict)


class EmbeddingConfigBundle(BaseModel):
    """一个项目里往往需要同时挂多套向量模型（比如文本用云端，图片用本地），
    用 name 区分，graph 运行时按需要选择。"""
    configs: list[EmbeddingConfig]

    def get(self, name: str) -> EmbeddingConfig:
        for c in self.configs:
            if c.name == name:
                return c
        raise KeyError(f"未找到名为 '{name}' 的向量配置")