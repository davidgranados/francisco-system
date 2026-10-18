from datetime import date
from decimal import Decimal
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings, today
from app.db import lock_inventory
from app.domain import rules
from app.domain.errors import DomainError
from app.domain.types import BoxStatus
from app.services import rates
from app.services.boxes import BoxView, get_box, view_of
from app.services.ledger import boxes_with_eggs


def _price_field() -> Any:
    return Field(default=None, gt=0, max_digits=12, decimal_places=2)


class PriceLine(BaseModel):
    usd: Decimal
    bs: Decimal


class PriceList(BaseModel):
    """Plantilla A for the box being sold."""

    day: date
    rate: Decimal
    rate_stale: bool
    box_number: int
    box: PriceLine
    carton: PriceLine
    half: PriceLine
    unit: PriceLine
    notice: str | None


class AdjustPricesInput(BaseModel):
    box_number: int | None = Field(default=None, description="Por defecto la caja que se vende")
    base_cost_usd: Decimal | None = Field(
        default=None,
        gt=0,
        decimal_places=2,
        description="Recalcular los precios como si la caja costara esto (ej. el costo nuevo)",
    )
    box_price: Decimal | None = _price_field()
    carton_price: Decimal | None = _price_field()
    half_price: Decimal | None = _price_field()
    unit_price: Decimal | None = _price_field()

    @model_validator(mode="after")
    def something_to_change(self) -> Self:
        manual = (self.box_price, self.carton_price, self.half_price, self.unit_price)
        if self.base_cost_usd is None and all(price is None for price in manual):
            raise ValueError("indique un costo base o al menos un precio")
        return self


async def price_list(session: AsyncSession, day: date | None = None) -> PriceList:
    day = day or today()
    holdings = await boxes_with_eggs(session)
    if not holdings:
        raise DomainError("No hay huevos en existencia: no hay precios que mostrar.")
    box = holdings[0][0]
    newest = holdings[-1][0]
    rate = await rates.rate_for(session, day)

    def line(usd: Decimal) -> PriceLine:
        return PriceLine(usd=usd, bs=rules.to_bs(usd, rate.rate))

    notice = None
    if newest.cost_usd > box.cost_usd:
        notice = (
            f"La Caja {newest.number} costó {rules.format_usd(newest.cost_usd)}, más que la "
            f"Caja {box.number}. Puede subir los precios con ajustar_precios."
        )
    return PriceList(
        day=day,
        rate=rate.rate,
        rate_stale=rate.stale,
        box_number=box.number,
        box=line(box.box_price),
        carton=line(box.carton_price),
        half=line(box.half_price),
        unit=line(box.unit_price),
        notice=notice,
    )


async def adjust_prices(session: AsyncSession, data: AdjustPricesInput) -> BoxView:
    await lock_inventory(session)
    if data.box_number is None:
        holdings = await boxes_with_eggs(session)
        if not holdings:
            raise DomainError("No hay cajas con huevos para cambiarles el precio.")
        box = holdings[0][0]
    else:
        box = await get_box(session, data.box_number)
    if box.status in (BoxStatus.FINISHED, BoxStatus.SETTLED):
        raise DomainError(f"La Caja {box.number} ya se acabó: no se le cambian los precios.")
    if data.base_cost_usd is not None:
        prices = rules.prices_from_cost(data.base_cost_usd, settings.markup)
        box.box_price, box.carton_price = prices.box, prices.carton
        box.half_price, box.unit_price = prices.half, prices.unit
    box.box_price = data.box_price or box.box_price
    box.carton_price = data.carton_price or box.carton_price
    box.half_price = data.half_price or box.half_price
    box.unit_price = data.unit_price or box.unit_price
    await session.flush()
    return await view_of(session, box)
