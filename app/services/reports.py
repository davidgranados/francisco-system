from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import rules
from app.domain.errors import DomainError
from app.domain.types import MovementKind, PaymentMethod
from app.models import (
    Contribution,
    EggMovement,
    Expense,
    Purchase,
    Sale,
    Settlement,
    SettlementShare,
)

ZERO = Decimal("0.00")


class PeriodInput(BaseModel):
    date_from: date
    date_to: date


class CashFlow(BaseModel):
    """Money that entered and left the business; partner pockets are not the business."""

    sales_usd: Decimal
    contributions_usd: Decimal
    purchases_usd: Decimal = Field(description="Compras pagadas por el negocio")
    expenses_usd: Decimal = Field(description="Gastos pagados por el negocio")
    reimbursements_usd: Decimal = Field(description="Gastos devueltos a socios")
    distributed_usd: Decimal = Field(description="Repartido a socios en cierres")
    entered_usd: Decimal
    left_usd: Decimal
    balance_usd: Decimal


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


def _between(
    column: Any, date_from: date | None, date_to: date | None
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if date_from is not None:
        conditions.append(column >= date_from)
    if date_to is not None:
        conditions.append(column <= date_to)
    return conditions


async def _sum(session: AsyncSession, column: Any, *conditions: ColumnElement[bool]) -> Decimal:
    return await session.scalar(select(func.coalesce(func.sum(column), ZERO)).where(*conditions))


async def cash_flow(
    session: AsyncSession, date_from: date | None = None, date_to: date | None = None
) -> CashFlow:
    sales = await _sum(
        session, Sale.amount_usd, ~Sale.voided, *_between(Sale.day, date_from, date_to)
    )
    contributions = await _sum(
        session, Contribution.amount_usd, *_between(Contribution.day, date_from, date_to)
    )
    purchases = await _sum(
        session,
        Purchase.total_usd,
        ~Purchase.voided,
        *_between(Purchase.day, date_from, date_to),
    )
    expenses = await _sum(
        session,
        Expense.amount_usd,
        Expense.paid_by_partner_id.is_(None),
        *_between(Expense.day, date_from, date_to),
    )
    reimbursements = await _sum(
        session,
        Expense.amount_usd,
        Expense.reimbursed_on.is_not(None),
        *_between(Expense.reimbursed_on, date_from, date_to),
    )
    distributed = await session.scalar(
        select(func.coalesce(func.sum(SettlementShare.amount_usd), ZERO))
        .join(Settlement, SettlementShare.settlement_id == Settlement.id)
        .where(*_between(Settlement.day, date_from, date_to))
    )
    entered = sales + contributions
    left = purchases + expenses + reimbursements + distributed
    return CashFlow(
        sales_usd=sales,
        contributions_usd=contributions,
        purchases_usd=purchases,
        expenses_usd=expenses,
        reimbursements_usd=reimbursements,
        distributed_usd=distributed,
        entered_usd=entered,
        left_usd=left,
        balance_usd=entered - left,
    )


async def summary(session: AsyncSession, data: PeriodInput) -> PeriodSummary:
    if data.date_to < data.date_from:
        raise DomainError("La fecha final es anterior a la inicial.")
    period = (data.date_from, data.date_to)
    sales = list(
        await session.scalars(select(Sale).where(~Sale.voided, *_between(Sale.day, *period)))
    )
    by_method: dict[PaymentMethod, Decimal] = {}
    for sale in sales:
        by_method[sale.payment_method] = by_method.get(sale.payment_method, ZERO) + sale.amount_usd
    losses = dict(
        (
            await session.execute(
                select(EggMovement.kind, func.sum(EggMovement.eggs))
                .where(EggMovement.kind != MovementKind.SALE, *_between(EggMovement.day, *period))
                .group_by(EggMovement.kind)
            )
        ).all()
    )
    purchases = list(
        await session.scalars(
            select(Purchase).where(~Purchase.voided, *_between(Purchase.day, *period))
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
        expenses_usd=await _sum(session, Expense.amount_usd, *_between(Expense.day, *period)),
        settlements_net_usd=await _sum(
            session, Settlement.net_profit_usd, *_between(Settlement.day, *period)
        ),
        cash=await cash_flow(session, *period),
    )
