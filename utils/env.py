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


class ENV:
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

    def __init__(self, env: str = "dev", env_dir: str = "env", base_path: Path = None):
        if self._initialized:
            return  # 避免重复初始化

        self.env = env or os.getenv("APP_ENV", "dev") or os.getenv("APP_ENV", "development")
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
    @property
    def server_host(self)-> str:
        return self.require("SERVER_HOST")
        
    @property
    def server_port(self) -> int:
        return int(self.require("SERVER_PORT"))

    @property
    def api_secret_key(self) -> str:
        return self.require("API_SECRET_KEY")
    
    @property
    def base_url(self)-> str:
        return self.require("BASE_URL")

    @property
    def is_prod(self) -> bool:
        return self.env == "prod" or self.env == "production"

    def __repr__(self):
        return f"<ENV env={self.env}>"

class ModelConfig(str, Enum):
    """模型配置项枚举类"""
    CLOUD_EMBEDDING_API_KEY = ENV.get("CLOUD_EMBEDDING_API_KEY"),
    CLOUD_EMBEDDING_API_URL = ENV.get("CLOUD_EMBEDDING_API_URL"),

    LOCAL_EMBEDDING_API_KEY = ENV.get("LOCAL_EMBEDDING_API_KEY"),
    LOCAL_EMBEDDING_API_URL = ENV.get("LOCAL_EMBEDDING_API_URL"),

# 全局单例，其他模块直接 import config 使用
ENV = ENV()
ModelConfig = ModelConfig()