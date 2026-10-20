from datetime import date, timedelta
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import rules
from app.domain.errors import DomainError
from app.domain.types import MovementKind, PaymentMethod
from app.models import EggMovement, Expense, Purchase, Sale, Settlement
from app.services import funds
from app.services.funds import between, sum_of

ZERO = Decimal("0.00")


class PeriodInput(BaseModel):
    date_from: date
    date_to: date


class FundFlow(BaseModel):
    opening_usd: Decimal
    entered_usd: Decimal
    left_usd: Decimal
    closing_usd: Decimal


def _fund_flow(opening: Decimal, entered: Decimal, left: Decimal) -> FundFlow:
    return FundFlow(
        opening_usd=opening,
        entered_usd=entered,
        left_usd=left,
        closing_usd=opening + entered - left,
    )


class CashFlow(BaseModel):
    """Money by fund over a period; utilidades and reimbursements leave the business."""

    capital: FundFlow = Field(description="Capital para comprar cajas")
    petty_cash: FundFlow = Field(description="Caja chica: ventas, gastos y cierres")
    savings: FundFlow = Field(description="Caja de ahorros: las reservas")
    movements: funds.Flows


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
    expenses_usd: Decimal
    settlements_net_usd: Decimal
    cash: CashFlow


async def cash_flow(
    session: AsyncSession, date_from: date | None = None, date_to: date | None = None
) -> CashFlow:
    before = (
        await funds.flows(session, until=date_from - timedelta(days=1))
        if date_from is not None
        else funds.Flows.none()
    )
    moved = await funds.flows(session, date_from, date_to)
    return CashFlow(
        capital=_fund_flow(before.capital_usd, moved.capital_in_usd, moved.capital_out_usd),
        petty_cash=_fund_flow(
            before.petty_cash_usd, moved.petty_cash_in_usd, moved.petty_cash_out_usd
        ),
        savings=_fund_flow(before.reserved_usd, moved.reserved_usd, ZERO),
        movements=moved,
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
        expenses_usd=await sum_of(session, Expense.amount_usd, *between(Expense.day, *period)),
        settlements_net_usd=await sum_of(
            session, Settlement.net_profit_usd, *between(Settlement.day, *period)
        ),
        cash=await cash_flow(session, *period),
    )
