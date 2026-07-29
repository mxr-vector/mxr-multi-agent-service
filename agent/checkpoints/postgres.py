"""
LangGraph PostgreSQL checkpointer 装配（问答多轮状态持久化）。

职责：
- 维护进程级唯一的 psycopg AsyncConnectionPool 与 AsyncPostgresSaver 惰性单例，
  与业务侧 SQLAlchemy/asyncpg 连接池并存、职责分离（本池仅供 checkpointer）；
- checkpoint 相关表由 `saver.setup()` 自动创建与演进，不手写 DDL 维护，
  业务层不得直接读写这些表（会话/消息查询一律走 rag.chat_sessions/chat_messages）；
- 提供 checkpoint TTL 清理：按 rag.chat_sessions.last_message_at 圈定过期
  thread 后逐一 adelete_thread，业务表数据不受影响。

生命周期由 infer.py 的 lifespan 驱动：启动时 open_checkpointer()，
关停时 close_checkpointer()；模块 import 期间不建立任何数据库连接。
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from core.source.postgres import PostgresConfig
from database.postgre_client import get_session
from database.rag.chat import ChatSessionRepository
from utils.env import ENV
from utils.logger import logger

# 进程级单例（lifespan 内初始化/释放，业务代码经 get_checkpointer 获取）
_pool: AsyncConnectionPool | None = None
_saver: AsyncPostgresSaver | None = None

# TTL 后台任务强引用（防 GC 提前回收，对齐 routers/rag/document.py 的模式）
_ttl_task: asyncio.Task | None = None

# TTL 清理循环间隔：每日一次
_TTL_LOOP_INTERVAL_SECONDS = 24 * 60 * 60


async def open_checkpointer() -> AsyncPostgresSaver:
    """
    打开 psycopg 连接池并完成 checkpointer 装配（幂等）。

    - 连接串用 PostgresConfig.psycopg_async_connection（原生 postgresql:// URI）；
    - AsyncPostgresSaver 要求连接 autocommit=True、dict_row、关闭预编译缓存；
    - checkpointer 写入频率低，池保持小额配置即可；
    - setup() 幂等：自动创建/迁移 checkpoint 相关表。
    """
    global _pool, _saver
    if _saver is not None:
        return _saver

    # Windows 守卫：psycopg 异步模式不支持 ProactorEventLoop。
    # 项目规范启动（infer.py reload=True / uvicorn --reload/--workers）下 uvicorn
    # 会选用 SelectorEventLoop；裸 `uvicorn infer:app` 会命中 Proactor，这里快速失败
    # 并给出可操作指引，避免连接池在后台无限重试。
    if sys.platform == "win32" and isinstance(
        asyncio.get_running_loop(), asyncio.ProactorEventLoop
    ):
        raise RuntimeError(
            "psycopg 异步模式不支持 Windows ProactorEventLoop："
            "请用 `uv run python infer.py`（reload）或 "
            "`uvicorn infer:app --reload` 启动（SelectorEventLoop）"
        )

    config = PostgresConfig.from_env()
    _pool = AsyncConnectionPool(
        conninfo=config.psycopg_async_connection,
        min_size=1,
        max_size=4,
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
    )
    # wait=True：启动期即验证连通性，连不上快速失败而非后台无限重试
    await _pool.open(wait=True, timeout=30)
    _saver = AsyncPostgresSaver(_pool)
    await _saver.setup()
    logger.info("[CHAT] checkpointer 已装配（psycopg 池 + AsyncPostgresSaver.setup）")
    return _saver


async def close_checkpointer() -> None:
    """关停时释放：取消 TTL 后台任务并关闭 psycopg 连接池（幂等）。"""
    global _pool, _saver, _ttl_task
    if _ttl_task is not None:
        _ttl_task.cancel()
        _ttl_task = None
    if _pool is not None:
        await _pool.close()
        _pool = None
    _saver = None
    logger.info("[CHAT] checkpointer 资源已释放")


def get_checkpointer() -> AsyncPostgresSaver:
    """获取已装配的 checkpointer；未初始化（lifespan 未执行）时快速失败。"""
    if _saver is None:
        raise RuntimeError("checkpointer 未初始化：须在应用 lifespan 启动后使用")
    return _saver


async def cleanup_expired_checkpoints() -> int:
    """
    执行一次 checkpoint TTL 清理，返回清理的 thread 数。

    以 rag.chat_sessions.last_message_at 早于 ENV.chat_checkpoint_ttl_days
    为过期判据（业务表是事实源），逐一删除对应 thread 的 checkpoint 数据；
    业务表中的会话与消息完整保留（过期会话续聊由 condense 回落业务表历史）。
    """
    saver = get_checkpointer()
    threshold = datetime.now(timezone.utc) - timedelta(
        days=ENV.chat_checkpoint_ttl_days
    )
    async with get_session() as session:
        expired_ids = await ChatSessionRepository(session).list_expired_ids(threshold)
    for session_id in expired_ids:
        await saver.adelete_thread(session_id.hex)
    if expired_ids:
        logger.info(
            f"[CHAT] checkpoint TTL 清理完成：{len(expired_ids)} 个过期 thread"
            f"（阈值 {ENV.chat_checkpoint_ttl_days} 天）"
        )
    return len(expired_ids)


async def _ttl_loop() -> None:
    """每日执行一次 TTL 清理；单轮失败仅告警，不中断循环。"""
    while True:
        try:
            await cleanup_expired_checkpoints()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"[CHAT] checkpoint TTL 清理失败，等待下一轮: {exc}")
        await asyncio.sleep(_TTL_LOOP_INTERVAL_SECONDS)


def start_ttl_task() -> None:
    """挂起 TTL 每日清理后台任务（模块级强引用持有，幂等）。"""
    global _ttl_task
    if _ttl_task is not None and not _ttl_task.done():
        return
    _ttl_task = asyncio.create_task(_ttl_loop())
