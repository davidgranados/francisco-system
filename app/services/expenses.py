from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import today
from app.db import lock_inventory
from app.domain import rules
from app.domain.errors import DomainError
from app.domain.types import Fund
from app.models import Expense, Settlement
from app.services import funds, partners, rates


class ExpenseInput(BaseModel):
    concept: str = Field(min_length=1, max_length=200)
    amount_usd: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    amount_bs: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=14,
        decimal_places=2,
        description="Monto en Bs; se pasa a $ con la tasa del día del gasto",
    )
    day: date | None = None
    paid_by_partner: str | None = Field(
        default=None, description="Socio que lo pagó de su bolsillo; vacío si pagó el negocio"
    )

    @model_validator(mode="after")
    def one_amount(self) -> Self:
        if (self.amount_usd is None) == (self.amount_bs is None):
            raise ValueError("indique el monto en $ o en Bs, uno de los dos")
        return self


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
    if data.amount_bs is not None:
        amount_usd, amount_bs = rules.to_usd(data.amount_bs, rate.rate), data.amount_bs
    else:
        assert data.amount_usd is not None
        amount_usd, amount_bs = data.amount_usd, rules.to_bs(data.amount_usd, rate.rate)
    expense = Expense(
        day=day,
        concept=data.concept,
        amount_usd=amount_usd,
        rate=rate.rate,
        amount_bs=amount_bs,
        paid_by_partner=payer,
    )
    session.add(expense)
    await session.flush()
    return expense_view(expense)


class Reimbursement(BaseModel):
    partner: str
    amount_usd: Decimal


def by_partner(expenses: Iterable[Expense]) -> list[Reimbursement]:
    """What these partner-paid expenses add up to per partner, in first-seen order."""
    owed: dict[str, Decimal] = {}
    for expense in expenses:
        assert expense.paid_by_partner is not None
        name = expense.paid_by_partner.name
        owed[name] = owed.get(name, Decimal("0.00")) + expense.amount_usd
    return [Reimbursement(partner=name, amount_usd=amount) for name, amount in owed.items()]


def _refusal(expense: Expense | None, expense_id: int, day: date) -> str | None:
    if expense is None:
        return f"No existe el gasto {expense_id}."
    if expense.paid_by_partner_id is None:
        return "Ese gasto lo pagó el negocio: no hay nada que devolver."
    if expense.reimbursed_on is not None:
        return f"Ese gasto ya se devolvió el {expense.reimbursed_on:%d/%m/%Y}."
    if day < expense.day:
        return (
            f"No se puede devolver el {day:%d/%m/%Y} un gasto del {expense.day:%d/%m/%Y}: "
            "la devolución no puede ser antes del gasto."
        )
    return None


async def reimburse(
    session: AsyncSession, expense_ids: Sequence[int], day: date, *, by_settlement: bool = False
) -> list[ExpenseView]:
    """Record that the caja chica paid these expenses back to their partners on `day`.

    All or nothing; only a cierre passes `by_settlement`, for the expenses it closes.
    """
    await lock_inventory(session)
    if day > today():
        raise DomainError(f"La fecha {day:%d/%m/%Y} es futura.")
    if not by_settlement:
        last = await session.scalar(select(func.max(Settlement.day)))
        if last is not None and day < last:
            raise DomainError(
                f"No se puede anotar una devolución del {day:%d/%m/%Y}: ya hay un cierre del "
                f"{last:%d/%m/%Y}. Use esa fecha o una posterior."
            )
    found = {
        expense.id: expense
        for expense in await session.scalars(select(Expense).where(Expense.id.in_(expense_ids)))
    }
    seen: set[int] = set()
    for expense_id in expense_ids:
        refusal = _refusal(found.get(expense_id), expense_id, day)
        if expense_id in seen:
            refusal = f"El gasto {expense_id} está dos veces: un gasto se devuelve una sola vez."
        if refusal is not None:
            raise DomainError(refusal)
        seen.add(expense_id)
    if not by_settlement:
        await funds.ensure_covered(
            session,
            funds.Operation.REIMBURSEMENT,
            [
                funds.Posting(day, Fund.PETTY_CASH, -e.amount_usd, funds.Kind.REIMBURSEMENT)
                for e in found.values()
            ],
        )
    for expense in found.values():
        expense.reimbursed_on = day
        expense.reimbursed_by_settlement = by_settlement
    await session.flush()
    return [expense_view(found[expense_id]) for expense_id in expense_ids]


async def reimburse_partner(session: AsyncSession, partner: str, day: date) -> list[ExpenseView]:
    """Give a partner back every expense they paid that is still owed to them."""
    payer = await partners.find_by_name(session, partner)
    owed = await session.scalars(
        select(Expense.id)
        .where(Expense.paid_by_partner_id == payer.id, Expense.reimbursed_on.is_(None))
        .order_by(Expense.day, Expense.id)
    )
    ids = list(owed)
    if not ids:
        raise DomainError(f"No hay gastos pendientes de devolver a {payer.name}.")
    return await reimburse(session, ids, day)


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
