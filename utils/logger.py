#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
多Agent协同系统日志模块

这个模块提供了统一的日志管理功能，包括：
1. 结构化日志记录
2. 多级别日志支持
3. 文件和控制台输出
4. 日志轮转和归档
5. 性能监控日志
6. Agent行为追踪
"""

import sys
from loguru import logger
from contextvars import ContextVar
from pathlib import Path

request_id_ctx = ContextVar("request_id", default="-")

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_ROOT = BASE_DIR / "logs"

logger.remove()


# 拦截器：handler 级 filter 注入 request_id。
# 用 filter 而非 logger.patch()：patch 只对当前实例生效，fastembed 等第三方库
# 在线程池中直接使用原始 loguru.logger 发日志时，其 record 缺少 extra[request_id]，
# 导致 LOG_FORMAT 里的 {extra[request_id]} 格式化抛 KeyError 并连带业务日志崩溃。
# filter 作用于每个 handler 的所有记录（无论来自哪个 logger 实例），先注入再格式化。
def inject_request_id(record):
    record["extra"].setdefault("request_id", request_id_ctx.get())
    return True


LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level:<8} | "
    "{extra[request_id]} | "
    "{message}"
)
# 控制台（enqueue=True：异步队列写 stdout，避免容器下 stdout 管道被采集端
# 拖慢时同步写日志阻塞事件循环、拖累全部请求；与下方文件 handler 口径一致）
logger.add(
    sys.stdout,
    format=LOG_FORMAT,
    level="INFO",
    filter=inject_request_id,
    enqueue=True,
)

# 所有日志
logger.add(
    LOG_ROOT / "{time:YYYY-MM-DD}/info.log",
    format=LOG_FORMAT,
    level="INFO",
    rotation="100 MB",  # 单文件最大 100MB
    retention="5 days",
    compression="zip",
    enqueue=True,
    filter=inject_request_id,
)


# 错误日志单独文件
logger.add(
    LOG_ROOT / "{time:YYYY-MM-DD}/error.log",
    format=LOG_FORMAT,
    level="ERROR",
    rotation="100 MB",  # 单文件最大 100MB
    retention="7 days",
    enqueue=True,
    filter=inject_request_id,
)
