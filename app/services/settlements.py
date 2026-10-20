from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import today
from app.db import lock_inventory
from app.domain import rules
from app.domain.errors import DomainError
from app.domain.types import BoxStatus
from app.models import Box, EggMovement, Expense, Partner, Settlement, SettlementShare
from app.services import funds, partners, rates
from app.services.boxes import BoxProfit, profit_of
from app.services.expenses import (
    ExpenseView,
    Reimbursement,
    by_partner,
    expense_view,
    reimburse,
    unsettled_until,
)
from app.services.pages import Page, PageRequest, fetch_page


class SettlementInput(BaseModel):
    day: date | None = Field(default=None, description="Fecha del cierre; por defecto hoy")
    reserve_usd: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    reserve_percent: Decimal | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Reserva como fracción de (ganancia de cajas - gastos), ej. 0.10",
    )
    reinvest_usd: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    reinvest_percent: Decimal | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Reinversión al capital como fracción de (ganancia de cajas - gastos)",
    )
    note: str | None = None

    @model_validator(mode="after")
    def one_amount_each(self) -> Self:
        if self.reserve_usd is not None and self.reserve_percent is not None:
            raise ValueError("indique la reserva en $ o en porcentaje, no las dos")
        if self.reinvest_usd is not None and self.reinvest_percent is not None:
            raise ValueError("indique la reinversión en $ o en porcentaje, no las dos")
        return self


class ShareView(BaseModel):
    partner: str
    share: Decimal
    amount_usd: Decimal


class SettlementPreview(BaseModel):
    """Plantilla H, plus the money check of Part 9 step 7 and where the money goes."""

    day: date
    boxes: list[BoxProfit]
    sales_usd: Decimal
    box_profit_usd: Decimal
    expenses: list[ExpenseView]
    expenses_usd: Decimal
    reserve_usd: Decimal = Field(description="Va a la caja de ahorros")
    reinvest_usd: Decimal = Field(description="Vuelve al capital")
    net_profit_usd: Decimal = Field(description="Utilidades: se reparten y salen del negocio")
    shares: list[ShareView]
    shares_total_usd: Decimal
    rate: Decimal
    rate_stale: bool
    amount_bs: Decimal
    next_box_money_usd: Decimal = Field(description="Capital devuelto: el costo de reponer")
    reimbursements: list[Reimbursement]
    petty_cash_after_usd: Decimal = Field(description="Caja chica al final del día del cierre")
    capital_after_usd: Decimal = Field(description="Capital al final del día del cierre")
    savings_after_usd: Decimal = Field(description="Caja de ahorros al final del día del cierre")
    note: str | None


class SettlementView(SettlementPreview):
    id: int


@dataclass(frozen=True)
class _Plan:
    preview: SettlementPreview
    settlement: Settlement
    boxes: list[Box]
    expenses: list[Expense]
    partners: list[Partner]


async def _closable_boxes(session: AsyncSession, day: date) -> list[tuple[Box, BoxProfit]]:
    finished = list(
        await session.scalars(
            select(Box)
            .where(Box.status == BoxStatus.FINISHED, Box.finished_on <= day)
            .order_by(Box.number)
        )
    )
    if not finished:
        return []
    following = {
        box.number: box
        for box in await session.scalars(
            select(Box).where(Box.number.in_([b.number + 1 for b in finished]))
        )
    }
    movements = await session.scalars(
        select(EggMovement).where(EggMovement.box_id.in_([b.id for b in finished]))
    )
    by_box: dict[int, list[EggMovement]] = {}
    for movement in movements:
        by_box.setdefault(movement.box_id, []).append(movement)
    return [
        (box, profit_of(box, following[box.number + 1], by_box.get(box.id, [])))
        for box in finished
        if box.number + 1 in following
    ]


async def _plan(session: AsyncSession, data: SettlementInput) -> _Plan:
    day = data.day or today()
    if day > today():
        raise DomainError(f"La fecha del cierre, {day:%d/%m/%Y}, es futura.")
    members = await partners.active_partners(session)
    if not members:
        raise DomainError("No hay socios registrados para repartir.")
    if sum(p.share for p in members) != 1:
        raise DomainError(
            "Los porcentajes de los socios no suman 100 %. Corríjalos antes del cierre."
        )
    closable = await _closable_boxes(session, day)
    expenses = await unsettled_until(session, day)
    if not closable and not expenses:
        raise DomainError(
            "No hay nada que cerrar: ninguna caja terminada con su caja siguiente comprada "
            "y ningún gasto pendiente."
        )
    profits = [profit for _, profit in closable]
    box_profit = sum((p.profit_usd for p in profits), Decimal("0.00"))
    expenses_usd = sum((e.amount_usd for e in expenses), Decimal("0.00"))
    base = box_profit - expenses_usd
    reserve = rules.set_aside(base, data.reserve_usd, data.reserve_percent)
    reinvest = rules.set_aside(base, data.reinvest_usd, data.reinvest_percent)
    if data.reinvest_percent is not None and data.reserve_percent is not None:
        # Two percents rounded apart can overshoot by a cent; the reinvestment absorbs it.
        reinvest = min(reinvest, max(base - reserve, Decimal("0.00")))
    if reserve + reinvest > max(base, Decimal("0.00")):
        raise DomainError(
            f"La reserva ({rules.format_usd(reserve)}) y la reinversión "
            f"({rules.format_usd(reinvest)}) pasan de la ganancia de las cajas menos los gastos "
            f"({rules.format_usd(base)}). Bájelas."
        )
    net = base - reserve - reinvest
    distributed = max(net, Decimal("0.00"))
    amounts = rules.split_shares(distributed, [p.share for p in members])
    rate = await rates.rate_for(session, day)
    reimbursements = by_partner(e for e in expenses if e.owed)
    next_box_money = sum((p.next_box_cost_usd for p in profits), Decimal("0.00"))
    settlement = Settlement(
        day=day,
        box_profit_usd=box_profit,
        expenses_usd=expenses_usd,
        reserve_usd=reserve,
        reinvest_usd=reinvest,
        net_profit_usd=net,
        rate=rate.rate,
        amount_bs=rules.to_bs(distributed, rate.rate),
        next_box_money_usd=next_box_money,
        note=data.note,
    )
    planned = funds.settlement_postings(
        settlement,
        distributed=sum(amounts, Decimal("0.00")),
        reimbursed=sum((r.amount_usd for r in reimbursements), Decimal("0.00")),
    )
    await funds.ensure_covered(session, funds.Operation.SETTLEMENT, planned)
    after = await funds.balances(session, funds.Cutoff(day), planned)
    preview = SettlementPreview(
        day=day,
        boxes=profits,
        sales_usd=sum((p.sales_usd for p in profits), Decimal("0.00")),
        box_profit_usd=box_profit,
        expenses=[expense_view(e) for e in expenses],
        expenses_usd=expenses_usd,
        reserve_usd=reserve,
        reinvest_usd=reinvest,
        net_profit_usd=net,
        shares=[
            ShareView(partner=p.name, share=p.share, amount_usd=amount)
            for p, amount in zip(members, amounts, strict=True)
        ],
        shares_total_usd=sum(amounts, Decimal("0.00")),
        rate=rate.rate,
        rate_stale=rate.stale,
        amount_bs=settlement.amount_bs,
        next_box_money_usd=next_box_money,
        reimbursements=reimbursements,
        petty_cash_after_usd=after.petty_cash_usd,
        capital_after_usd=after.capital_usd,
        savings_after_usd=after.savings_usd,
        note=data.note,
    )
    return _Plan(
        preview=preview,
        settlement=settlement,
        boxes=[box for box, _ in closable],
        expenses=expenses,
        partners=members,
    )


async def preview_settlement(session: AsyncSession, data: SettlementInput) -> SettlementPreview:
    return (await _plan(session, data)).preview


async def execute_settlement(session: AsyncSession, data: SettlementInput) -> SettlementView:
    await lock_inventory(session)
    plan = await _plan(session, data)
    preview = plan.preview
    settlement = plan.settlement
    session.add(settlement)
    await session.flush()
    for partner, share in zip(plan.partners, preview.shares, strict=True):
        session.add(
            SettlementShare(
                settlement_id=settlement.id,
                partner_id=partner.id,
                share=share.share,
                amount_usd=share.amount_usd,
            )
        )
    for box in plan.boxes:
        rules.check_box_transition(box.status, BoxStatus.SETTLED)
        box.status = BoxStatus.SETTLED
        box.settlement_id = settlement.id
    for expense in plan.expenses:
        expense.settlement_id = settlement.id
    await session.flush()
    await reimburse(
        session, [e.id for e in plan.expenses if e.owed], preview.day, by_settlement=True
    )
    return SettlementView(id=settlement.id, **preview.model_dump())


def _newest_first() -> Select[tuple[Settlement]]:
    return (
        select(Settlement)
        .options(selectinload(Settlement.shares))
        .order_by(Settlement.day.desc(), Settlement.id.desc())
    )


async def list_settlements(session: AsyncSession, limit: int = 10) -> list[SettlementView]:
    rows = await session.scalars(_newest_first().limit(limit))
    return [await _stored_view(session, settlement) for settlement in rows]


async def settlements_page(session: AsyncSession, request: PageRequest) -> Page[SettlementView]:
    rows, total = await fetch_page(session, _newest_first(), request)
    return Page[SettlementView].of([await _stored_view(session, s) for s in rows], total, request)


async def _stored_view(session: AsyncSession, settlement: Settlement) -> SettlementView:
    boxes = list(await session.scalars(select(Box).where(Box.settlement_id == settlement.id)))
    following = {
        box.number: box
        for box in await session.scalars(
            select(Box).where(Box.number.in_([b.number + 1 for b in boxes]))
        )
    }
    movements = list(
        await session.scalars(
            select(EggMovement).where(EggMovement.box_id.in_([b.id for b in boxes]))
        )
    )
    profits = [
        profit_of(box, following[box.number + 1], [m for m in movements if m.box_id == box.id])
        for box in sorted(boxes, key=lambda b: b.number)
    ]
    expenses = list(
        await session.scalars(
            select(Expense)
            .where(Expense.settlement_id == settlement.id)
            .order_by(Expense.day, Expense.id)
        )
    )
    after = await funds.balances(session, funds.Cutoff(settlement.day, settlement.id))
    return SettlementView(
        id=settlement.id,
        day=settlement.day,
        boxes=profits,
        sales_usd=sum((p.sales_usd for p in profits), Decimal("0.00")),
        box_profit_usd=settlement.box_profit_usd,
        expenses=[expense_view(e) for e in expenses],
        expenses_usd=settlement.expenses_usd,
        reserve_usd=settlement.reserve_usd,
        reinvest_usd=settlement.reinvest_usd,
        net_profit_usd=settlement.net_profit_usd,
        shares=[
            ShareView(partner=s.partner.name, share=s.share, amount_usd=s.amount_usd)
            for s in settlement.shares
        ],
        shares_total_usd=sum((s.amount_usd for s in settlement.shares), Decimal("0.00")),
        rate=settlement.rate,
        rate_stale=False,
        amount_bs=settlement.amount_bs,
        next_box_money_usd=settlement.next_box_money_usd,
        reimbursements=by_partner(e for e in expenses if e.reimbursed_by_settlement),
        petty_cash_after_usd=after.petty_cash_usd,
        capital_after_usd=after.capital_usd,
        savings_after_usd=after.savings_usd,
        note=settlement.note,
    )
