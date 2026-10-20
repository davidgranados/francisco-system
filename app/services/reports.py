from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import rules
from app.domain.errors import DomainError
from app.domain.types import Fund, MovementKind, PaymentMethod
from app.models import EggMovement, Expense, Purchase, Sale, Settlement
from app.services import funds
from app.services.funds import FundFlow, Kind

ZERO = Decimal("0.00")


def between(column: Any, since: date, until: date) -> list[ColumnElement[bool]]:
    return [column >= since, column <= until]


async def sum_of(session: AsyncSession, column: Any, *conditions: ColumnElement[bool]) -> Decimal:
    return await session.scalar(select(func.coalesce(func.sum(column), ZERO)).where(*conditions))


class PeriodInput(BaseModel):
    date_from: date
    date_to: date


class CashFlow(BaseModel):
    """Money by fund over a period; utilidades and reimbursements leave the business."""

    capital: FundFlow = Field(description="Capital para comprar cajas")
    petty_cash: FundFlow = Field(description="Caja chica: ventas, gastos y cierres")
    savings: FundFlow = Field(description="Caja de ahorros: las reservas")


class PeriodSummary(BaseModel):
    date_from: date
    date_to: date
    sales_count: int
    eggs_sold: int
    sales_usd: Decimal
    sales_bs: Decimal
    sales_by_payment_method: dict[PaymentMethod, Decimal]
    broken_eggs: int
    gifted_eggs: int
    shrinkage_eggs: int
    boxes_bought: int
    purchases_usd: Decimal
    expenses_usd: Decimal = Field(
        description="Lo que salió de la caja chica en gastos: los del negocio y los devueltos a "
        "socios"
    )
    pending_reimbursement_usd: Decimal = Field(
        description="Gastos que pagó un socio y al final del período no se le habían devuelto"
    )
    settlements_net_usd: Decimal
    cash: CashFlow


async def cash_flow(
    session: AsyncSession, date_from: date | None = None, date_to: date | None = None
) -> CashFlow:
    moved = await funds.flows(session, date_from, date_to)
    return CashFlow(
        capital=moved[Fund.CAPITAL],
        petty_cash=moved[Fund.PETTY_CASH],
        savings=moved[Fund.SAVINGS],
    )


async def summary(session: AsyncSession, data: PeriodInput) -> PeriodSummary:
    if data.date_to < data.date_from:
        raise DomainError("La fecha final es anterior a la inicial.")
    period = (data.date_from, data.date_to)
    sales = list(
        await session.scalars(select(Sale).where(~Sale.voided, *between(Sale.day, *period)))
    )
    by_method: dict[PaymentMethod, Decimal] = {}
    for sale in sales:
        by_method[sale.payment_method] = by_method.get(sale.payment_method, ZERO) + sale.amount_usd
    losses = dict(
        (
            await session.execute(
                select(EggMovement.kind, func.sum(EggMovement.eggs))
                .where(EggMovement.kind != MovementKind.SALE, *between(EggMovement.day, *period))
                .group_by(EggMovement.kind)
            )
        ).all()
    )
    purchases = list(
        await session.scalars(
            select(Purchase).where(~Purchase.voided, *between(Purchase.day, *period))
        )
    )
    cash = await cash_flow(session, *period)
    spent = cash.petty_cash.by_kind
    return PeriodSummary(
        date_from=data.date_from,
        date_to=data.date_to,
        sales_count=len(sales),
        eggs_sold=sum(rules.eggs_in(s.cartons, s.halves, s.units, s.boxes) for s in sales),
        sales_usd=sum((s.amount_usd for s in sales), ZERO),
        sales_bs=sum((s.amount_bs for s in sales), ZERO),
        sales_by_payment_method=by_method,
        broken_eggs=int(losses.get(MovementKind.BROKEN, 0)),
        gifted_eggs=int(losses.get(MovementKind.GIFT, 0)),
        shrinkage_eggs=int(losses.get(MovementKind.SHRINKAGE, 0)),
        boxes_bought=sum(p.box_count for p in purchases),
        purchases_usd=sum((p.total_usd for p in purchases), ZERO),
        expenses_usd=-sum(
            (spent.get(kind, ZERO) for kind in (Kind.EXPENSE, Kind.REIMBURSEMENT)), ZERO
        ),
        pending_reimbursement_usd=await sum_of(
            session,
            Expense.amount_usd,
            Expense.paid_by_partner_id.is_not(None),
            Expense.day <= data.date_to,
            or_(Expense.reimbursed_on.is_(None), Expense.reimbursed_on > data.date_to),
        ),
        settlements_net_usd=await sum_of(
            session, Settlement.net_profit_usd, *between(Settlement.day, *period)
        ),
        cash=cash,
    )
