from datetime import date
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import today
from app.db import lock_inventory
from app.domain import rules
from app.domain.errors import DomainError
from app.domain.types import BoxStatus, MovementKind, PaymentMethod
from app.models import Sale
from app.services import rates
from app.services.ledger import boxes_with_eggs, release_movements, take_eggs
from app.services.purchases import VoidInput


class SaleInput(BaseModel):
    cartons: int = Field(default=0, ge=0, description="Cartones de 30 huevos")
    halves: int = Field(default=0, ge=0, description="Medios cartones de 15 huevos")
    units: int = Field(default=0, ge=0, description="Huevos sueltos")
    payment_method: PaymentMethod
    day: date | None = Field(default=None, description="Fecha de la venta; por defecto hoy")
    charged_usd: Decimal | None = Field(
        default=None,
        gt=0,
        decimal_places=2,
        description="Lo cobrado en $ si fue distinto al precio de lista (descuento)",
    )
    charged_bs: Decimal | None = Field(
        default=None,
        gt=0,
        decimal_places=2,
        description="Lo cobrado en Bs, si el cliente pagó un monto exacto en bolívares",
    )
    customer: str | None = Field(default=None, max_length=120)
    note: str | None = None

    @model_validator(mode="after")
    def has_eggs_and_one_price(self) -> Self:
        if rules.eggs_in(self.cartons, self.halves, self.units) == 0:
            raise ValueError("la venta debe tener al menos un huevo")
        if self.charged_usd is not None and self.charged_bs is not None:
            raise ValueError("indique el monto cobrado en $ o en Bs, no los dos")
        return self


class SalePart(BaseModel):
    box_number: int
    eggs: int
    amount_usd: Decimal


class SaleView(BaseModel):
    id: int
    day: date
    rate: Decimal
    cartons: int
    halves: int
    units: int
    eggs: int
    amount_usd: Decimal
    amount_bs: Decimal
    payment_method: PaymentMethod
    customer: str | None
    note: str | None
    voided: bool
    void_reason: str | None
    parts: list[SalePart]


class RegisteredSale(SaleView):
    list_amount_usd: Decimal
    rate_stale: bool
    finished_boxes: list[int]
    eggs_left: int


def _view(sale: Sale) -> SaleView:
    return SaleView(
        id=sale.id,
        day=sale.day,
        rate=sale.rate,
        cartons=sale.cartons,
        halves=sale.halves,
        units=sale.units,
        eggs=rules.eggs_in(sale.cartons, sale.halves, sale.units),
        amount_usd=sale.amount_usd,
        amount_bs=sale.amount_bs,
        payment_method=sale.payment_method,
        customer=sale.customer,
        note=sale.note,
        voided=sale.voided,
        void_reason=sale.void_reason,
        parts=[
            SalePart(box_number=m.box.number, eggs=m.eggs, amount_usd=m.amount_usd or Decimal(0))
            for m in sale.movements
        ],
    )


async def _load(session: AsyncSession, sale_id: int) -> Sale:
    sale = await session.scalar(
        select(Sale)
        .where(Sale.id == sale_id)
        .options(selectinload(Sale.movements))
        .execution_options(populate_existing=True)
    )
    if sale is None:
        raise DomainError(f"No existe la venta {sale_id}.")
    return sale


async def record_sale(session: AsyncSession, data: SaleInput) -> RegisteredSale:
    """Price the sale with the open box's prices and take its eggs oldest box first."""
    await lock_inventory(session)
    day = data.day or today()
    eggs = rules.eggs_in(data.cartons, data.halves, data.units)
    holdings = await boxes_with_eggs(session)
    rules.allocate_fifo(eggs, [(box.number, left) for box, left in holdings])
    rate = await rates.rate_for(session, day)
    pricing_box = holdings[0][0]
    prices = rules.Prices(
        box=pricing_box.box_price,
        carton=pricing_box.carton_price,
        half=pricing_box.half_price,
        unit=pricing_box.unit_price,
    )
    listed = rules.list_amount(prices, data.cartons, data.halves, data.units)
    if data.charged_bs is not None:
        amount_usd, amount_bs = rules.to_usd(data.charged_bs, rate.rate), data.charged_bs
    else:
        amount_usd = data.charged_usd if data.charged_usd is not None else listed
        amount_bs = rules.to_bs(amount_usd, rate.rate)
    sale = Sale(
        day=day,
        rate=rate.rate,
        cartons=data.cartons,
        halves=data.halves,
        units=data.units,
        amount_usd=amount_usd,
        amount_bs=amount_bs,
        payment_method=data.payment_method,
        customer=data.customer,
        note=data.note,
        movements=[],
    )
    session.add(sale)
    await session.flush()
    movements = await take_eggs(session, eggs, day, MovementKind.SALE, sale=sale)
    left = sum(remaining for _, remaining in await boxes_with_eggs(session))
    return RegisteredSale(
        **_view(await _load(session, sale.id)).model_dump(),
        list_amount_usd=listed,
        rate_stale=rate.stale,
        finished_boxes=[m.box.number for m in movements if m.box.status == BoxStatus.FINISHED],
        eggs_left=left,
    )


async def void_sale(session: AsyncSession, sale_id: int, data: VoidInput) -> SaleView:
    await lock_inventory(session)
    sale = await _load(session, sale_id)
    if sale.voided:
        raise DomainError(f"La venta {sale_id} ya estaba anulada.")
    view = _view(sale)
    await release_movements(session, list(sale.movements))
    sale.voided = True
    sale.void_reason = data.reason
    await session.flush()
    return view.model_copy(update={"voided": True, "void_reason": data.reason})


async def list_sales(session: AsyncSession, day: date | None = None) -> list[SaleView]:
    rows = await session.scalars(
        select(Sale)
        .where(Sale.day == (day or today()))
        .options(selectinload(Sale.movements))
        .order_by(Sale.id)
    )
    return [_view(sale) for sale in rows]
