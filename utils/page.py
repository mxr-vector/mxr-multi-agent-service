import math
from typing import Generic, Sequence, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    """统一分页结果契约：items 为当前页数据，total 为过滤后的总量。"""

    items: list[T]
    total: int
    page: int
    size: int
    pages: int


async def paginate(
    session: AsyncSession,
    stmt: Select,
    page: int,
    size: int,
) -> tuple[Sequence, int]:
    """
    在异步会话上对已构建（含过滤/排序）的 select 语句分页。

    total 用同一语句的子查询做 COUNT，确保反映过滤后的集合而非全表；
    items 用 limit/offset 取当前页。调用方负责在 stmt 上应用 WHERE 与 ORDER BY。
    """
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await session.execute(stmt.limit(size).offset((page - 1) * size))
    items = result.scalars().all()
    return items, total or 0


def build_page_result(items: list, total: int, page: int, size: int) -> PageResult:
    """由已序列化的 items 与总量构建 PageResult，计算总页数 pages。"""
    pages = math.ceil(total / size) if size > 0 else 0
    return PageResult(items=items, total=total, page=page, size=size, pages=pages)
