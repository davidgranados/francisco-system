from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings, today
from app.db import lock_inventory
from app.domain import rules
from app.domain.errors import DomainError
from app.domain.types import BoxStatus, Fund, PaymentMethod
from app.models import Box, Purchase
from app.services import funds, rates
from app.services.boxes import BoxView, views_of
from app.services.ledger import boxes_with_eggs


class PurchaseInput(BaseModel):
    box_count: int = Field(ge=1, le=200, description="Cuántas cajas se compraron")
    cost_per_box_usd: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_method: PaymentMethod
    day: date | None = Field(default=None, description="Fecha de la compra; por defecto hoy")
    supplier: str | None = Field(default=None, max_length=120)
    note: str | None = None


class VoidInput(BaseModel):
    reason: str = Field(min_length=1, description="Por qué se anula")


class PurchaseView(BaseModel):
    id: int
    day: date
    supplier: str | None
    box_count: int
    cost_per_box_usd: Decimal
    rate: Decimal
    total_usd: Decimal
    total_bs: Decimal
    payment_method: PaymentMethod
    note: str | None
    voided: bool
    void_reason: str | None
    boxes: list[BoxView]


class RegisteredPurchase(PurchaseView):
    rate_stale: bool
    price_notice: str | None = Field(
        description="Aviso cuando la caja que se está vendiendo costó menos que la nueva"
    )


async def _view(session: AsyncSession, purchase: Purchase) -> PurchaseView:
    return PurchaseView(
        id=purchase.id,
        day=purchase.day,
        supplier=purchase.supplier,
        box_count=purchase.box_count,
        cost_per_box_usd=purchase.cost_per_box_usd,
        rate=purchase.rate,
        total_usd=purchase.total_usd,
        total_bs=purchase.total_bs,
        payment_method=purchase.payment_method,
        note=purchase.note,
        voided=purchase.voided,
        void_reason=purchase.void_reason,
        boxes=await views_of(session, list(purchase.boxes)),
    )


async def _load(session: AsyncSession, purchase_id: int) -> Purchase:
    purchase = await session.scalar(
        select(Purchase)
        .where(Purchase.id == purchase_id)
        .options(selectinload(Purchase.boxes))
        .execution_options(populate_existing=True)
    )
    if purchase is None:
        raise DomainError(f"No existe la compra {purchase_id}.")
    return purchase


def _price_notice(selling: Box | None, cost: Decimal) -> str | None:
    if selling is None or selling.cost_usd >= cost:
        return None
    return (
        f"La Caja {selling.number} se sigue vendiendo con sus precios "
        f"(cartón {rules.format_usd(selling.carton_price)}), calculados con su costo de "
        f"{rules.format_usd(selling.cost_usd)}. La nueva caja cuesta {rules.format_usd(cost)}: "
        "ofrezca subir los precios de la caja abierta con ajustar_precios."
    )


async def register_purchase(session: AsyncSession, data: PurchaseInput) -> RegisteredPurchase:
    await lock_inventory(session)
    day = data.day or today()
    rate = await rates.rate_for(session, day)
    total_usd = data.cost_per_box_usd * data.box_count
    capital, _ = await funds.lowest_balance(session, Fund.CAPITAL, since=day)
    if capital < total_usd:
        raise DomainError(
            f"El capital disponible es {rules.format_usd(capital)} y la compra cuesta "
            f"{rules.format_usd(total_usd)}. Falta un aporte de "
            f"{rules.format_usd(total_usd - capital)}: regístrelo con registrar_aporte y vuelva "
            "a registrar la compra."
        )
    holdings = await boxes_with_eggs(session)
    selling = holdings[0][0] if holdings else None
    purchase = Purchase(
        day=day,
        supplier=data.supplier,
        box_count=data.box_count,
        cost_per_box_usd=data.cost_per_box_usd,
        rate=rate.rate,
        total_usd=total_usd,
        total_bs=rules.to_bs(total_usd, rate.rate),
        payment_method=data.payment_method,
        note=data.note,
    )
    session.add(purchase)
    last_number = await session.scalar(select(func.max(Box.number))) or 0
    prices = rules.prices_from_cost(data.cost_per_box_usd, settings.markup)
    for offset in range(1, data.box_count + 1):
        session.add(
            Box(
                purchase=purchase,
                number=last_number + offset,
                cost_usd=data.cost_per_box_usd,
                box_price=prices.box,
                carton_price=prices.carton,
                half_price=prices.half,
                unit_price=prices.unit,
                status=BoxStatus.STOCKED,
            )
        )
    await session.flush()
    view = await _view(session, await _load(session, purchase.id))
    return RegisteredPurchase(
        **view.model_dump(),
        rate_stale=rate.stale,
        price_notice=_price_notice(selling, data.cost_per_box_usd),
    )


async def void_purchase(session: AsyncSession, purchase_id: int, data: VoidInput) -> PurchaseView:
    """Void a purchase whose boxes were never touched; later boxes are renumbered down."""
    await lock_inventory(session)
    purchase = await _load(session, purchase_id)
    if purchase.voided:
        raise DomainError(f"La compra {purchase_id} ya estaba anulada.")
    touched = [box.number for box in purchase.boxes if box.status != BoxStatus.STOCKED]
    if touched:
        raise DomainError(
            "No se puede anular: ya se vendió o rompió de la caja "
            + ", ".join(str(n) for n in touched)
            + ". Anule primero esas ventas."
        )
    count = len(purchase.boxes)
    last_removed = max(box.number for box in purchase.boxes)
    for box in purchase.boxes:
        await session.delete(box)
    await session.flush()
    later = await session.scalars(select(Box).where(Box.number > last_removed).order_by(Box.number))
    for box in later:
        box.number -= count
        await session.flush()
    purchase.voided = True
    purchase.void_reason = data.reason
    await session.flush()
    return await _view(session, await _load(session, purchase_id))


async def list_purchases(session: AsyncSession, limit: int = 20) -> list[PurchaseView]:
    rows = await session.scalars(
        select(Purchase)
        .options(selectinload(Purchase.boxes))
        .order_by(Purchase.day.desc(), Purchase.id.desc())
        .limit(limit)
    )
    return [await _view(session, purchase) for purchase in rows]
