from dataclasses import dataclass
from functools import cached_property
from utils.env import ENV


@dataclass(frozen=True)
class PostgresConfig:
    """
    PostgreSQL 配置
    """

    host: str
    port: int
    database: str
    username: str
    password: str

    @cached_property
    def connection(self) -> str:
        """
        SQLAlchemy连接串
        """
        return (
            f"postgresql+psycopg://"
            f"{self.username}:{self.password}"
            f"@{self.host}:{self.port}"
            f"/{self.database}"
        )

    @cached_property
    def async_connection(self) -> str:
        """
        异步连接
        """
        return (
            f"postgresql+asyncpg://"
            f"{self.username}:{self.password}"
            f"@{self.host}:{self.port}"
            f"/{self.database}"
        )

    @classmethod
    def from_env(cls):
        return cls(
            host=ENV.postgres_host,
            port=ENV.postgres_port,
            database=ENV.postgres_db,
            username=ENV.postgres_user,
            password=ENV.postgres_password,
        )
