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

# 文件

LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level:<8} | "
    "{extra[request_id]} | "
    "{message}"
)
# 控制台
logger.add(
    sys.stdout,
    format=LOG_FORMAT,
    level="INFO",
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
)


# 错误日志单独文件
logger.add(
    LOG_ROOT / "{time:YYYY-MM-DD}/error.log",
    format=LOG_FORMAT,
    level="ERROR",
    rotation="100 MB",  # 单文件最大 100MB
    retention="7 days",
    enqueue=True,
)


# 拦截器：自动注入 request_id
def inject_request_id(record):
    record["extra"]["request_id"] = request_id_ctx.get()
    return record


logger = logger.patch(inject_request_id)
