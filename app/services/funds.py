"""The business's three funds, derived from the rows that move money so they never drift.

Capital buys eggs; aportes fill it and each cierre returns the closed boxes' replacement cost
plus the reinvestment. The caja chica receives sales and pays expenses, reimbursements and
the cierre. The caja de ahorros keeps the reserves.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contribution, Expense, Partner, Purchase, Sale, Settlement, SettlementShare

ZERO = Decimal("0.00")


class Flows(BaseModel):
    """Money that moved over a period, each figure dated by when the money moved."""

    contributions_usd: Decimal
    purchases_usd: Decimal
    sales_usd: Decimal
    expenses_usd: Decimal
    reimbursements_usd: Decimal
    returned_to_capital_usd: Decimal
    reinvested_usd: Decimal
    reserved_usd: Decimal
    distributed_usd: Decimal

    @classmethod
    def none(cls) -> "Flows":
        return cls(**dict.fromkeys(cls.model_fields, ZERO))

    @property
    def capital_in_usd(self) -> Decimal:
        return self.contributions_usd + self.returned_to_capital_usd + self.reinvested_usd

    @property
    def capital_out_usd(self) -> Decimal:
        return self.purchases_usd

    @property
    def petty_cash_in_usd(self) -> Decimal:
        return self.sales_usd

    @property
    def petty_cash_out_usd(self) -> Decimal:
        return (
            self.expenses_usd
            + self.reimbursements_usd
            + self.returned_to_capital_usd
            + self.reinvested_usd
            + self.reserved_usd
            + self.distributed_usd
        )

    @property
    def capital_usd(self) -> Decimal:
        return self.capital_in_usd - self.capital_out_usd

    @property
    def petty_cash_usd(self) -> Decimal:
        return self.petty_cash_in_usd - self.petty_cash_out_usd


class PartnerContribution(BaseModel):
    partner: str
    amount_usd: Decimal


class FundBalances(BaseModel):
    capital_usd: Decimal
    petty_cash_usd: Decimal
    savings_usd: Decimal
    contributed_by_partner: list[PartnerContribution]


def between(column: Any, since: date | None, until: date | None) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if since is not None:
        conditions.append(column >= since)
    if until is not None:
        conditions.append(column <= until)
    return conditions


async def sum_of(session: AsyncSession, column: Any, *conditions: ColumnElement[bool]) -> Decimal:
    return await session.scalar(select(func.coalesce(func.sum(column), ZERO)).where(*conditions))


async def flows(
    session: AsyncSession, since: date | None = None, until: date | None = None
) -> Flows:
    """Expenses a partner paid leave the business when they are reimbursed, not before."""
    settled = between(Settlement.day, since, until)
    return Flows(
        contributions_usd=await sum_of(
            session, Contribution.amount_usd, *between(Contribution.day, since, until)
        ),
        purchases_usd=await sum_of(
            session, Purchase.total_usd, ~Purchase.voided, *between(Purchase.day, since, until)
        ),
        sales_usd=await sum_of(
            session, Sale.amount_usd, ~Sale.voided, *between(Sale.day, since, until)
        ),
        expenses_usd=await sum_of(
            session,
            Expense.amount_usd,
            Expense.paid_by_partner_id.is_(None),
            *between(Expense.day, since, until),
        ),
        reimbursements_usd=await sum_of(
            session,
            Expense.amount_usd,
            Expense.reimbursed_on.is_not(None),
            *between(Expense.reimbursed_on, since, until),
        ),
        returned_to_capital_usd=await sum_of(session, Settlement.next_box_money_usd, *settled),
        reinvested_usd=await sum_of(session, Settlement.reinvest_usd, *settled),
        reserved_usd=await sum_of(session, Settlement.reserve_usd, *settled),
        distributed_usd=await session.scalar(
            select(func.coalesce(func.sum(SettlementShare.amount_usd), ZERO))
            .join(Settlement, SettlementShare.settlement_id == Settlement.id)
            .where(*settled)
        ),
    )


async def balances(session: AsyncSession, until: date | None = None) -> FundBalances:
    """What each fund holds at the end of `until`, or now."""
    moved = await flows(session, until=until)
    by_partner = await session.execute(
        select(Partner.name, func.sum(Contribution.amount_usd))
        .join(Partner, Contribution.partner_id == Partner.id)
        .where(*between(Contribution.day, None, until))
        .group_by(Partner.id, Partner.name)
        .order_by(Partner.id)
    )
    return FundBalances(
        capital_usd=moved.capital_usd,
        petty_cash_usd=moved.petty_cash_usd,
        savings_usd=moved.reserved_usd,
        contributed_by_partner=[
            PartnerContribution(partner=name, amount_usd=amount) for name, amount in by_partner
        ],
    )
