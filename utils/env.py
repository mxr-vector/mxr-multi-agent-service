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
    def is_prod(self) -> bool:
        return self.env == "prod" or self.env == "production"

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
        """原始 EMBEDDING_PROVIDER 字符串；合法性由 embedding 模块的 EmbeddingProvider 负责校验"""
        return self.require("EMBEDDING_PROVIDER")

    @property
    def embedding_model_name(self) -> str:
        return self.require("EMBEDDING_MODEL_NAME")

    """
    Chat 模型相关配置（vLLM OpenAI 兼容接口）
    """

    @property
    def chat_api_key(self) -> str:
        return self.require("CHAT_API_KEY")

    @property
    def chat_api_url(self) -> str:
        return self.require("CHAT_API_URL")

    @property
    def chat_model_name(self) -> str:
        return self.require("CHAT_MODEL_NAME")

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


# 全局单例，其他模块直接 import config 使用
ENV = ENV_CONFIG()
