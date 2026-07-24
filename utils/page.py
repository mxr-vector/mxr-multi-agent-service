from typing import TypeVar, Generic, Sequence, Optional
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.sql import ClauseElement

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int


def paginate(
    session: Session,
    query,
    page: int,
    size: int,
    order_by: Optional[list[ClauseElement]] = None,
) -> tuple[Sequence, int]:
    total = session.scalar(select(func.count()).select_from(query.subquery()))

    if order_by:
        query = query.order_by(*order_by)

    items = session.execute(query.offset((page - 1) * size).limit(size)).scalars().all()
    return items, total
