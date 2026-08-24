"""
env.py - 环境配置加载工具类
用法:
    from config import config
    print(config.db_host)
"""

from enum import Enum
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv


class ENV_CONFIG:
    """
    环境配置管理类（单例模式）
    根据 APP_ENV 自动加载 env/.env.{env} 文件
    """

    _instance: Optional["ENV"] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        # 单例：全局只加载一次配置
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, env_dir: str = "env", base_path: Path = None):
        if self._initialized:
            return  # 避免重复初始化

        self.env = os.getenv("APP_ENV", "development")
        self.base_path = base_path or Path(__file__).resolve().parent.parent
        self.env_dir = self.base_path / env_dir

        self._load_env_files()
        self._initialized = True

    def _load_env_files(self):
        """先加载公共配置 .env，再加载环境专属配置并覆盖"""
        common_file = self.env_dir / ".env"
        env_file = self.env_dir / f".env.{self.env}"

        if not env_file.exists():
            raise FileNotFoundError(f"配置文件不存在: {env_file}")

        if common_file.exists():
            load_dotenv(dotenv_path=common_file)

        load_dotenv(dotenv_path=env_file, override=True)
        print(f"[ENV] 当前环境: {self.env} | 已加载: {env_file.name}")

    # ---------- 通用取值方法 ----------
    @staticmethod
    def get(key: str, default=None) -> str:
        return os.getenv(key, default)

    @staticmethod
    def get_int(key: str, default: int = 0) -> int:
        return int(os.getenv(key, default))

    @staticmethod
    def get_bool(key: str, default: bool = False) -> bool:
        val = os.getenv(key)
        if val is None:
            return default
        return val.strip().lower() in ("true", "1", "yes", "on")

    @staticmethod
    def require(key: str) -> str:
        """必须存在的配置项，不存在则抛异常"""
        val = os.getenv(key)
        if val is None:
            raise KeyError(f"缺少必需的环境变量: {key}")
        return val

    # ---------- 针对你项目的常用属性（可按需增删） ----------
    """
    基础相关配置
    """

    @property
    def server_host(self) -> str:
        return self.require("SERVER_HOST")

    @property
    def server_port(self) -> int:
        return int(self.require("SERVER_PORT"))

    @property
    def api_secret_key(self) -> str:
        return self.require("API_SECRET_KEY")

    @property
    def base_url(self) -> str:
        return self.require("BASE_URL")

    @property
    def jwt_secret_key(self) -> str:
        """JWT 签名密钥，与 API_SECRET_KEY 严格分离"""
        return self.require("JWT_SECRET_KEY")

    @property
    def jwt_expire_hours(self) -> int:
        """JWT token 有效期（小时）"""
        return int(self.require("JWT_EXPIRE_HOURS"))

    @property
    def upload_max_size_mb(self) -> int:
        """文档上传大小上限（MB），超限在解析前即拒绝"""
        return int(self.require("UPLOAD_MAX_SIZE_MB"))

    @property
    def upload_dir(self) -> Path:
        """全局上传文件存储根目录；相对路径基于项目根解析，默认 data。"""
        raw = self.get("UPLOAD_DIR", "data")
        path = Path(raw)
        return path if path.is_absolute() else self.base_path / path

    @property
    def is_prod(self) -> bool:
        return self.env == "prod" or self.env == "production"

    @property
    def wiki_enabled(self) -> bool:
        """Whether the optional topic-navigation tool is exposed to the agent."""
        return self.get_bool("WIKI_ENABLED", True)

    @property
    def multihop_enabled(self) -> bool:
        """Controlled per-hop evidence drill-down for explicit multihop requests."""
        return self.get_bool("MULTIHOP_ENABLED", True)

    @property
    def entity_index_enabled(self) -> bool:
        """Entity bridge index expansion channel (offline index, zero online LLM)."""
        return self.get_bool("ENTITY_INDEX_ENABLED", True)

    def __repr__(self):
        return f"<ENV env={self.env}>"

    """
    向量模型相关配置
    """

    @property
    def embedding_api_key(self) -> str:
        return self.require("EMBEDDING_API_KEY")

    @property
    def embedding_api_url(self) -> str:
        return self.require("EMBEDDING_API_URL")

    @property
    def embedding_provider(self) -> str:
        """原始 EMBEDDING_PROVIDER 字符串；合法性由 embedding 模块的工厂注册表负责校验"""
        return self.require("EMBEDDING_PROVIDER")

    @property
    def embedding_model_name(self) -> str:
        return self.require("EMBEDDING_MODEL_NAME")

    @property
    def embedding_timeout(self) -> float:
        """embedding HTTP 请求超时（秒）；服务不可达时快速失败，避免向量化作业长时间挂起。"""
        return float(self.get("EMBEDDING_TIMEOUT", 60))

    @property
    def embedding_max_retries(self) -> int:
        """embedding HTTP 请求重试次数；调小可让故障快速暴露（默认 1）。"""
        return int(self.get("EMBEDDING_MAX_RETRIES", 1))

    """
    Rerank / Chat / Rewrite / Visual 模型相关配置已迁至数据库（sys_model_config），
    经配置快照 core.config_snapshot.CFG 读取并支持免重启热更新；此处不再暴露对应 property。
    EMBEDDING_* 因换模型即毁向量库、与基础设施配置同属部署级钉死项，仍保留在 env。
    """

    """
    数据库相关配置
    """

    @property
    def postgres_host(self) -> str:
        return self.require("POSTGRES_HOST") or "localhost"

    @property
    def postgres_port(self) -> int:
        return int(self.require("POSTGRES_PORT")) or 5432

    @property
    def postgres_db(self) -> str:
        return self.require("POSTGRES_DB") or "multi_agent_db"

    @property
    def postgres_user(self) -> str:
        return self.require("POSTGRES_USER") or "postgres"

    @property
    def postgres_password(self) -> str:
        return self.require("POSTGRES_PASSWORD") or "postgres"

    """
    向量数据库(Qdrant)相关配置
    """

    @property
    def qdrant_host(self) -> str:
        return self.require("QDRANT_HOST") or "127.0.0.1"

    @property
    def qdrant_port(self) -> int:
        return int(self.require("QDRANT_PORT")) or 6333

    @property
    def qdrant_api_key(self) -> str:
        return self.require("QDRANT_API_KEY")

    @property
    def qdrant_https(self) -> bool:
        """是否使用 https 连接 Qdrant，默认 False"""
        return self.get_bool("QDRANT_HTTPS", False)

    """
    RAG 检索相关配置
    RAG 标量阈值（RAG_CANDIDATE_POOL_SIZE / RAG_FINAL_TOP_K / RAG_REFLECT_ROUND_CAP）
    已迁至 sys_config 内置参数，经配置快照 CFG 读取并支持热更新；
    BM25 缓存目录属本机部署拓扑，仍保留在 env。
    """

    @property
    def bm25_cache_dir(self) -> Path:
        """BM25 稀疏模型缓存目录；相对路径基于项目根解析，默认 model/hf。"""
        raw = self.get("BM25_CACHE_DIR", "model/hf")
        path = Path(raw)
        return path if path.is_absolute() else self.base_path / path

    """
    AI 问答（chat 会话）相关配置
    CHAT_CHECKPOINT_TTL_DAYS / CHAT_HISTORY_MAX_MESSAGES 已迁至 sys_config 内置参数，
    经配置快照 CFG 读取并支持热更新；此处不再暴露对应 property。
    """


# 全局单例，其他模块直接 import config 使用
ENV = ENV_CONFIG()
