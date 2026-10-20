import json
from datetime import date
from decimal import Decimal

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings, today
from app.domain.errors import DomainError
from app.domain.rules import FOUR_PLACES, format_number
from app.domain.types import RateSource
from app.models import ExchangeRate
from app.services.pages import Page, PageRequest, fetch_page


class RateUnavailable(Exception):
    pass


class RateView(BaseModel):
    day: date
    rate: Decimal
    source: RateSource
    rate_day: date = Field(description="Fecha de la tasa guardada que se usó")
    stale: bool = Field(description="True si no hay tasa de ese día y se usó una anterior")


class SetRateInput(BaseModel):
    rate: Decimal = Field(gt=0, max_digits=14, decimal_places=4)
    day: date | None = None


async def fetch_bcv_rate() -> Decimal:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(settings.bcv_api_url)
            response.raise_for_status()
        rate = json.loads(response.text, parse_float=Decimal)["promedio"]
        value = Decimal(str(rate)).quantize(FOUR_PLACES)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, ArithmeticError) as error:
        raise RateUnavailable(str(error)) from error
    if value <= 0:
        raise RateUnavailable(f"non-positive rate {value}")
    return value


def _view(row: ExchangeRate, day: date) -> RateView:
    return RateView(
        day=day, rate=row.rate, source=row.source, rate_day=row.day, stale=row.day != day
    )


async def rate_for(session: AsyncSession, day: date) -> RateView:
    """The BCV rate of `day`: stored, else fetched (today only), else the last stored before it."""
    stored = await session.scalar(select(ExchangeRate).where(ExchangeRate.day == day))
    if stored is not None:
        return _view(stored, day)
    if day >= today():
        try:
            value = await fetch_bcv_rate()
        except RateUnavailable:
            pass
        else:
            await session.execute(
                insert(ExchangeRate)
                .values(day=day, rate=value, source=RateSource.BCV_API)
                .on_conflict_do_nothing(index_elements=[ExchangeRate.day])
            )
            row = await session.scalar(select(ExchangeRate).where(ExchangeRate.day == day))
            assert row is not None
            return _view(row, day)
    previous = await session.scalar(
        select(ExchangeRate).where(ExchangeRate.day < day).order_by(ExchangeRate.day.desc())
    )
    if previous is None:
        raise DomainError(
            f"No tengo la tasa BCV del {day:%d/%m/%Y} ni una anterior. "
            "Dígame la tasa del día y la guardo."
        )
    return _view(previous, day)


async def set_rate(session: AsyncSession, data: SetRateInput) -> RateView:
    day = data.day or today()
    await session.execute(
        insert(ExchangeRate)
        .values(day=day, rate=data.rate, source=RateSource.MANUAL)
        .on_conflict_do_update(
            index_elements=[ExchangeRate.day],
            set_={"rate": data.rate, "source": RateSource.MANUAL},
        )
    )
    row = await session.scalar(
        select(ExchangeRate)
        .where(ExchangeRate.day == day)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return _view(row, day)


class ExchangeRateRow(BaseModel):
    day: date
    rate: Decimal
    source: RateSource


async def rates_page(session: AsyncSession, request: PageRequest) -> Page[ExchangeRateRow]:
    """The rates stored, newest day first."""
    query = select(ExchangeRate).order_by(ExchangeRate.day.desc())
    rows, total = await fetch_page(session, query, request)
    items = [ExchangeRateRow(day=r.day, rate=r.rate, source=r.source) for r in rows]
    return Page[ExchangeRateRow].of(items, total, request)


def describe(rate: RateView) -> str:
    text = f"Bs {format_number(rate.rate, 4)}"
    return f"{text} (del {rate.rate_day:%d/%m}, no hay tasa de hoy)" if rate.stale else text
