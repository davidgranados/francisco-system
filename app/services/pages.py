from typing import Self

from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


class PageRequest(BaseModel):
    page: int = Field(default=1, ge=1, description="Página, desde 1")
    page_size: int = Field(default=20, ge=1, le=100, description="Filas por página, hasta 100")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int

    @classmethod
    def of(cls, items: list[T], total: int, request: PageRequest) -> Self:
        return cls(items=items, total=total, page=request.page, page_size=request.page_size)


async def fetch_page[M](
    session: AsyncSession, query: Select[tuple[M]], request: PageRequest
) -> tuple[list[M], int]:
    """One page of the query's rows, and how many rows the whole query has."""
    total = await session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = await session.scalars(query.limit(request.page_size).offset(request.offset))
    return list(rows), total or 0
