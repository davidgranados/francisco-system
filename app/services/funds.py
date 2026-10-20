"""The business's three funds, read from a journal derived from the rows that move money.

Capital buys eggs; aportes fill it and each cierre returns the closed boxes' replacement cost
plus the reinvestment. The caja chica receives sales and pays expenses, reimbursements and
the cierre. The caja de ahorros keeps the reserves. Nothing stores a balance, so a void or a
correction never leaves one out of date.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel
from sqlalchemy import (
    ColumnElement,
    Integer,
    Select,
    String,
    Subquery,
    case,
    func,
    literal,
    select,
    union_all,
)
from sqlalchemy import tuple_ as row
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.types import Fund
from app.models import Contribution, Expense, Partner, Purchase, Sale, Settlement, SettlementShare

ZERO = Decimal("0.00")


class Kind(StrEnum):
    """Why money moved; a move between two funds posts the same kind on both."""

    CONTRIBUTION = "contribution"
    PURCHASE = "purchase"
    SALE = "sale"
    EXPENSE = "expense"
    REIMBURSEMENT = "reimbursement"
    RETURNED_TO_CAPITAL = "returned_to_capital"
    REINVESTMENT = "reinvestment"
    RESERVE = "reserve"
    DISTRIBUTION = "distribution"


@dataclass(frozen=True)
class Posting:
    """One movement of one fund: positive enters it, negative leaves it."""

    day: date
    fund: Fund
    amount_usd: Decimal
    kind: Kind
    settlement_id: int = 0
    """The cierre that made it, or 0; a cierre closes its day after everything else."""


@dataclass(frozen=True)
class Cutoff:
    """Up to the end of `day`, or right after cierre `settlement_id` when it is given."""

    day: date
    settlement_id: int | None = None


class FundFlow(BaseModel):
    opening_usd: Decimal
    entered_usd: Decimal
    left_usd: Decimal
    closing_usd: Decimal
    by_kind: dict[Kind, Decimal]


class PartnerContribution(BaseModel):
    partner: str
    amount_usd: Decimal


class FundBalances(BaseModel):
    capital_usd: Decimal
    petty_cash_usd: Decimal
    savings_usd: Decimal
    contributed_by_partner: list[PartnerContribution]


SETTLEMENT_MOVES: tuple[tuple[Kind, str, Fund], ...] = (
    (Kind.RETURNED_TO_CAPITAL, "next_box_money_usd", Fund.CAPITAL),
    (Kind.REINVESTMENT, "reinvest_usd", Fund.CAPITAL),
    (Kind.RESERVE, "reserve_usd", Fund.SAVINGS),
)
"""What a cierre moves out of the caja chica besides utilidades and reimbursements, and where."""


def _leg(day: Any, fund: Fund, amount: Any, kind: Kind, settlement_id: Any = None) -> Select[Any]:
    return select(
        day.label("day"),
        literal(fund.value, String).label("fund"),
        amount.label("amount_usd"),
        literal(kind.value, String).label("kind"),
        (literal(0, Integer) if settlement_id is None else settlement_id).label("settlement_id"),
    )


def _journal() -> Subquery:
    reimbursed_by = case((Settlement.day == Expense.reimbursed_on, Settlement.id), else_=0)
    legs = [
        _leg(Contribution.day, Fund.CAPITAL, Contribution.amount_usd, Kind.CONTRIBUTION),
        _leg(Purchase.day, Fund.CAPITAL, -Purchase.total_usd, Kind.PURCHASE).where(
            ~Purchase.voided
        ),
        _leg(Sale.day, Fund.PETTY_CASH, Sale.amount_usd, Kind.SALE).where(~Sale.voided),
        _leg(Expense.day, Fund.PETTY_CASH, -Expense.amount_usd, Kind.EXPENSE).where(
            Expense.paid_by_partner_id.is_(None)
        ),
        _leg(
            Expense.reimbursed_on,
            Fund.PETTY_CASH,
            -Expense.amount_usd,
            Kind.REIMBURSEMENT,
            reimbursed_by,
        )
        .outerjoin(Settlement, Expense.settlement_id == Settlement.id)
        .where(Expense.reimbursed_on.is_not(None)),
        _leg(
            Settlement.day,
            Fund.PETTY_CASH,
            -SettlementShare.amount_usd,
            Kind.DISTRIBUTION,
            Settlement.id,
        )
        .join(Settlement, SettlementShare.settlement_id == Settlement.id)
        .where(SettlementShare.amount_usd != 0),
    ]
    for kind, attribute, to in SETTLEMENT_MOVES:
        column = getattr(Settlement, attribute)
        legs.append(
            _leg(Settlement.day, Fund.PETTY_CASH, -column, kind, Settlement.id).where(column != 0)
        )
        legs.append(_leg(Settlement.day, to, column, kind, Settlement.id).where(column != 0))
    return union_all(*legs).subquery("postings")


def settlement_postings(
    settlement: Settlement, distributed: Decimal, reimbursed: Decimal
) -> list[Posting]:
    """The postings an unsaved cierre will make, the same ones `_journal` reads once saved."""
    day = settlement.day
    postings = [
        Posting(day, Fund.PETTY_CASH, -distributed, Kind.DISTRIBUTION),
        Posting(day, Fund.PETTY_CASH, -reimbursed, Kind.REIMBURSEMENT),
    ]
    for kind, attribute, to in SETTLEMENT_MOVES:
        amount = getattr(settlement, attribute)
        postings += [Posting(day, Fund.PETTY_CASH, -amount, kind), Posting(day, to, amount, kind)]
    return [p for p in postings if p.amount_usd != 0]


def _until(journal: Subquery, at: Cutoff) -> ColumnElement[bool]:
    if at.settlement_id is None:
        return journal.c.day <= at.day
    return row(journal.c.day, journal.c.settlement_id) <= (at.day, at.settlement_id)


async def balances(
    session: AsyncSession, at: Cutoff | None = None, planned: Sequence[Posting] = ()
) -> FundBalances:
    """What each fund holds at `at`, or now, plus postings not saved yet."""
    journal = _journal()
    totals = select(journal.c.fund, func.sum(journal.c.amount_usd)).group_by(journal.c.fund)
    if at is not None:
        totals = totals.where(_until(journal, at))
    held = dict.fromkeys(Fund, ZERO)
    for fund, amount in await session.execute(totals):
        held[Fund(fund)] += amount
    for posting in planned:
        held[posting.fund] += posting.amount_usd
    by_partner = await session.execute(
        select(Partner.name, func.sum(Contribution.amount_usd))
        .join(Partner, Contribution.partner_id == Partner.id)
        .where(*([] if at is None else [Contribution.day <= at.day]))
        .group_by(Partner.id, Partner.name)
        .order_by(Partner.id)
    )
    return FundBalances(
        capital_usd=held[Fund.CAPITAL],
        petty_cash_usd=held[Fund.PETTY_CASH],
        savings_usd=held[Fund.SAVINGS],
        contributed_by_partner=[
            PartnerContribution(partner=name, amount_usd=amount) for name, amount in by_partner
        ],
    )


async def flows(
    session: AsyncSession, since: date | None = None, until: date | None = None
) -> dict[Fund, FundFlow]:
    """Per fund: what it held before `since`, what entered and left by `until`, and why."""
    journal = _journal()
    up_to = [] if until is None else [journal.c.day <= until]
    within = up_to if since is None else [*up_to, journal.c.day >= since]
    before = literal(False) if since is None else journal.c.day < since
    amount = journal.c.amount_usd
    totals = await session.execute(
        select(
            journal.c.fund,
            func.coalesce(func.sum(amount).filter(before), ZERO),
            func.coalesce(func.sum(amount).filter(*within, amount > 0), ZERO),
            func.coalesce(-func.sum(amount).filter(*within, amount < 0), ZERO),
        )
        .where(*up_to)
        .group_by(journal.c.fund)
    )
    kinds = await session.execute(
        select(journal.c.fund, journal.c.kind, func.sum(amount))
        .where(*within)
        .group_by(journal.c.fund, journal.c.kind)
    )
    by_kind: dict[Fund, dict[Kind, Decimal]] = {fund: {} for fund in Fund}
    for fund, kind, total in kinds:
        by_kind[Fund(fund)][Kind(kind)] = total
    moved = dict.fromkeys(Fund, (ZERO, ZERO, ZERO))
    for fund, opening, entered, left in totals:
        moved[Fund(fund)] = (opening, entered, left)
    return {
        fund: FundFlow(
            opening_usd=opening,
            entered_usd=entered,
            left_usd=left,
            closing_usd=opening + entered - left,
            by_kind=by_kind[fund],
        )
        for fund, (opening, entered, left) in moved.items()
    }


async def lowest_balance(
    session: AsyncSession, fund: Fund, since: date, planned: Sequence[Posting] = ()
) -> tuple[Decimal, date]:
    """The fund's lowest end-of-day balance from `since` on, and its day, with `planned` added."""
    journal = _journal()
    mine = journal.c.fund == fund.value
    balance = await session.scalar(
        select(func.coalesce(func.sum(journal.c.amount_usd), ZERO)).where(
            mine, journal.c.day < since
        )
    )
    by_day: dict[date, Decimal] = dict.fromkeys([since], ZERO)
    for day, amount in await session.execute(
        select(journal.c.day, func.sum(journal.c.amount_usd))
        .where(mine, journal.c.day >= since)
        .group_by(journal.c.day)
    ):
        by_day[day] = by_day.get(day, ZERO) + amount
    for posting in planned:
        if posting.fund == fund:
            by_day[posting.day] = by_day.get(posting.day, ZERO) + posting.amount_usd
    lowest: tuple[Decimal, date] | None = None
    for day in sorted(by_day):
        balance += by_day[day]
        if lowest is None or balance < lowest[0]:
            lowest = (balance, day)
    assert lowest is not None
    return lowest
