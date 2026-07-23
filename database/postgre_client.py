from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.source.postgres import PostgresConfig


@lru_cache(maxsize=1)
def get_async_engine() -> AsyncEngine:
    """
    获取进程级唯一的异步 PostgreSQL 引擎单例。

    连接串由 PostgresConfig.async_connection（postgresql+asyncpg://...）决定、
    进程内固定不变，引擎内部维护连接池可复用，因此用 lru_cache 缓存单例，
    避免重复建连与重复读取配置（对齐 get_qdrant_client 的单例约定）。
    业务代码统一通过 session 工厂获取会话，勿直接实例化引擎。
    """
    config = PostgresConfig.from_env()
    return create_async_engine(config.async_connection)


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    获取进程级唯一的异步会话工厂单例。

    绑定在共享引擎上，所有实体模块共用同一连接池；关闭 expire_on_commit
    以便提交后仍可读取返回对象的属性（用于回写 API 响应）。
    """
    return async_sessionmaker(
        bind=get_async_engine(),
        expire_on_commit=False,
    )


def get_session() -> AsyncSession:
    """
    从共享工厂创建一个异步会话，供 service 层在 `async with` 中使用。
    """
    return get_session_factory()()
