from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import today
from app.domain import rules
from app.domain.errors import DomainError
from app.models import Expense
from app.services import partners, rates


class ExpenseInput(BaseModel):
    concept: str = Field(min_length=1, max_length=200)
    amount_usd: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    day: date | None = None
    paid_by_partner: str | None = Field(
        default=None, description="Socio que lo pagó de su bolsillo; vacío si pagó el negocio"
    )


class ReimburseInput(BaseModel):
    day: date | None = Field(default=None, description="Fecha de la devolución; por defecto hoy")


class ExpenseView(BaseModel):
    id: int
    day: date
    concept: str
    amount_usd: Decimal
    rate: Decimal
    amount_bs: Decimal
    paid_by_partner: str | None
    reimbursed_on: date | None
    settled: bool


def expense_view(expense: Expense) -> ExpenseView:
    return ExpenseView(
        id=expense.id,
        day=expense.day,
        concept=expense.concept,
        amount_usd=expense.amount_usd,
        rate=expense.rate,
        amount_bs=expense.amount_bs,
        paid_by_partner=expense.paid_by_partner.name if expense.paid_by_partner else None,
        reimbursed_on=expense.reimbursed_on,
        settled=expense.settlement_id is not None,
    )


async def record_expense(session: AsyncSession, data: ExpenseInput) -> ExpenseView:
    day = data.day or today()
    rate = await rates.rate_for(session, day)
    payer = (
        await partners.find_by_name(session, data.paid_by_partner) if data.paid_by_partner else None
    )
    expense = Expense(
        day=day,
        concept=data.concept,
        amount_usd=data.amount_usd,
        rate=rate.rate,
        amount_bs=rules.to_bs(data.amount_usd, rate.rate),
        paid_by_partner=payer,
    )
    session.add(expense)
    await session.flush()
    return expense_view(expense)


async def mark_reimbursed(
    session: AsyncSession, expense_id: int, data: ReimburseInput
) -> ExpenseView:
    expense = await session.get(Expense, expense_id)
    if expense is None:
        raise DomainError(f"No existe el gasto {expense_id}.")
    if expense.paid_by_partner_id is None:
        raise DomainError("Ese gasto lo pagó el negocio: no hay nada que devolver.")
    if expense.reimbursed_on is not None:
        raise DomainError(f"Ese gasto ya se devolvió el {expense.reimbursed_on:%d/%m/%Y}.")
    expense.reimbursed_on = data.day or today()
    await session.flush()
    return expense_view(expense)


async def unsettled_until(session: AsyncSession, day: date) -> list[Expense]:
    rows = await session.scalars(
        select(Expense)
        .where(Expense.settlement_id.is_(None), Expense.day <= day)
        .order_by(Expense.day, Expense.id)
    )
    return list(rows)


async def pending(session: AsyncSession) -> list[ExpenseView]:
    """Expenses not yet in a settlement, and partner-paid ones not yet given back."""
    rows = await session.scalars(
        select(Expense)
        .where(
            or_(
                Expense.settlement_id.is_(None),
                Expense.paid_by_partner_id.is_not(None) & Expense.reimbursed_on.is_(None),
            )
        )
        .order_by(Expense.day, Expense.id)
    )
    return [expense_view(expense) for expense in rows]
