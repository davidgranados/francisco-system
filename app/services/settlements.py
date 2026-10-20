from dataclasses import dataclass
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
from app.domain.types import BoxStatus
from app.models import Box, EggMovement, Expense, Partner, Settlement, SettlementShare
from app.services import funds, partners, rates
from app.services.boxes import BoxProfit, profit_of
from app.services.expenses import ExpenseView, expense_view, unsettled_until


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


class Reimbursement(BaseModel):
    partner: str
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
    reimbursements: dict[str, Decimal] = {}
    for expense in expenses:
        if expense.paid_by_partner and expense.reimbursed_on is None:
            name = expense.paid_by_partner.name
            reimbursements[name] = reimbursements.get(name, Decimal(0)) + expense.amount_usd
    next_box_money = sum((p.next_box_cost_usd for p in profits), Decimal("0.00"))
    before = await funds.balances(session, until=day)
    to_capital = next_box_money + reinvest
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
        amount_bs=rules.to_bs(distributed, rate.rate),
        next_box_money_usd=next_box_money,
        reimbursements=[Reimbursement(partner=k, amount_usd=v) for k, v in reimbursements.items()],
        petty_cash_after_usd=before.petty_cash_usd
        - to_capital
        - reserve
        - sum(amounts, Decimal("0.00"))
        - sum(reimbursements.values(), Decimal("0.00")),
        capital_after_usd=before.capital_usd + to_capital,
        savings_after_usd=before.savings_usd + reserve,
        note=data.note,
    )
    return _Plan(
        preview=preview, boxes=[box for box, _ in closable], expenses=expenses, partners=members
    )


async def preview_settlement(session: AsyncSession, data: SettlementInput) -> SettlementPreview:
    return (await _plan(session, data)).preview


async def execute_settlement(session: AsyncSession, data: SettlementInput) -> SettlementView:
    await lock_inventory(session)
    plan = await _plan(session, data)
    preview = plan.preview
    settlement = Settlement(
        day=preview.day,
        box_profit_usd=preview.box_profit_usd,
        expenses_usd=preview.expenses_usd,
        reserve_usd=preview.reserve_usd,
        reinvest_usd=preview.reinvest_usd,
        net_profit_usd=preview.net_profit_usd,
        rate=preview.rate,
        amount_bs=preview.amount_bs,
        next_box_money_usd=preview.next_box_money_usd,
        note=preview.note,
    )
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
        if expense.paid_by_partner_id is not None and expense.reimbursed_on is None:
            expense.reimbursed_on = preview.day
    await session.flush()
    return SettlementView(id=settlement.id, **preview.model_dump())


async def list_settlements(session: AsyncSession, limit: int = 10) -> list[SettlementView]:
    rows = await session.scalars(
        select(Settlement)
        .options(selectinload(Settlement.shares))
        .order_by(Settlement.day.desc(), Settlement.id.desc())
        .limit(limit)
    )
    return [await _stored_view(session, settlement) for settlement in rows]


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
            select(Expense).where(Expense.settlement_id == settlement.id).order_by(Expense.day)
        )
    )
    after = await funds.balances(session, until=settlement.day)
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
        reimbursements=[
            Reimbursement(partner=e.paid_by_partner.name, amount_usd=e.amount_usd)
            for e in expenses
            if e.paid_by_partner
        ],
        petty_cash_after_usd=after.petty_cash_usd,
        capital_after_usd=after.capital_usd,
        savings_after_usd=after.savings_usd,
        note=settlement.note,
    )
