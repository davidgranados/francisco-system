"""Giving a partner back an expense they paid: only one module writes it, with its rules."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.agent.tools import dispatch
from app.config import today
from app.db import SessionLocal
from app.domain.errors import DomainError
from app.domain.types import PaymentMethod
from app.services import (
    contributions,
    expenses,
    funds,
    purchases,
    rates,
    sales,
    settlements,
)
from tests.conftest import Call
from tests.test_tools import SPEAKER

DAY = date(2026, 10, 14)


@pytest.fixture(autouse=True)
async def week(call: Call, two_partners: None) -> None:
    """Box 1 sold out and box 2 bought, the caja chica holds $ 75,00 of sales."""
    await call(rates.set_rate, rates.SetRateInput(day=DAY, rate=D("877.90")))
    await call(
        contributions.record_contribution,
        contributions.ContributionInput(partner="Socio A", amount_usd=D("123.00"), day=DAY),
    )
    for cost in ("60.00", "63.00"):
        await call(
            purchases.register_purchase,
            purchases.PurchaseInput(
                day=DAY,
                box_count=1,
                cost_per_box_usd=D(cost),
                payment_method=PaymentMethod.CASH_USD,
            ),
        )
    await call(
        sales.record_sale,
        sales.SaleInput(day=DAY, cartons=12, payment_method=PaymentMethod.CASH_USD),
    )


async def _paid_by(call: Call, partner: str, amount: str, day: date = DAY) -> int:
    expense = await call(
        expenses.record_expense,
        expenses.ExpenseInput(
            day=day, concept="Transporte", amount_usd=D(amount), paid_by_partner=partner
        ),
    )
    return int(expense.id)


async def _petty_cash(call: Call) -> D:
    return D((await call(funds.balances)).petty_cash_usd)


async def test_a_reimbursement_before_the_expense_or_in_the_future_is_refused(
    call: Call,
) -> None:
    expense = await _paid_by(call, "Socio B", "1.50")

    with pytest.raises(DomainError, match="no puede ser antes del gasto"):
        await call(expenses.reimburse, [expense], DAY - timedelta(days=1))
    with pytest.raises(DomainError, match="es futura"):
        await call(expenses.reimburse, [expense], today() + timedelta(days=1))

    assert await _petty_cash(call) == D("75.00")
    assert [e.reimbursed_on for e in await call(expenses.pending)] == [None]


async def test_an_expense_is_given_back_once_and_a_bad_id_gives_back_none(call: Call) -> None:
    first = await _paid_by(call, "Socio B", "1.50")
    second = await _paid_by(call, "Socio B", "2.00")

    with pytest.raises(DomainError, match="No existe el gasto 99"):
        await call(expenses.reimburse, [first, 99], DAY)
    with pytest.raises(DomainError, match="una sola vez"):
        await call(expenses.reimburse, [second, second], DAY)
    assert await _petty_cash(call) == D("75.00")

    await call(expenses.reimburse, [first], DAY)
    with pytest.raises(DomainError, match="ya se devolvió el 14/10/2026"):
        await call(expenses.reimburse, [first], DAY)
    assert await _petty_cash(call) == D("73.50")


async def test_a_reimbursement_dated_before_the_last_cierre_is_refused(call: Call) -> None:
    earlier = DAY - timedelta(days=2)
    await call(rates.set_rate, rates.SetRateInput(day=earlier, rate=D("876.80")))
    await call(settlements.execute_settlement, settlements.SettlementInput(day=DAY))
    await call(
        sales.record_sale,
        sales.SaleInput(day=DAY, cartons=1, payment_method=PaymentMethod.CASH_USD),
    )
    expense = await _paid_by(call, "Socio B", "1.50", day=earlier)

    with pytest.raises(DomainError, match="ya hay un cierre del 14/10/2026"):
        await call(expenses.reimburse, [expense], DAY - timedelta(days=1))
    [given_back] = await call(expenses.reimburse, [expense], DAY)
    assert given_back.reimbursed_on == DAY


async def test_an_expense_given_back_before_the_cierre_is_not_paid_again_by_it(
    call: Call,
) -> None:
    early = await _paid_by(call, "Socio B", "1.50")
    await _paid_by(call, "Socio A", "0.50")
    await call(expenses.reimburse, [early], DAY)
    closing = settlements.SettlementInput(day=DAY)

    preview = await call(settlements.preview_settlement, closing)
    await call(settlements.execute_settlement, closing)
    [stored] = await call(settlements.list_settlements)

    assert (preview.expenses_usd, preview.net_profit_usd) == (D("2.00"), D("10.00"))
    paid_by_cierre = [("Socio A", D("0.50"))]
    assert [(r.partner, r.amount_usd) for r in preview.reimbursements] == paid_by_cierre
    assert [(r.partner, r.amount_usd) for r in stored.reimbursements] == paid_by_cierre
    assert stored.petty_cash_after_usd == preview.petty_cash_after_usd == D("0.00")


async def test_the_bot_gives_a_partner_back_everything_owed_to_them_at_once(call: Call) -> None:
    await _paid_by(call, "Socio A", "1.50")
    await _paid_by(call, "Socio A", "2.00")
    owed_to_b = await _paid_by(call, "Socio B", "0.40")

    outcome = await dispatch(
        "marcar_gasto_devuelto", {"socio": "yo", "fecha": DAY.isoformat()}, SessionLocal, SPEAKER
    )

    assert not outcome.is_error, outcome.content
    owed = [e.id for e in await call(expenses.pending) if e.reimbursed_on is None]
    assert owed == [owed_to_b]
    assert await _petty_cash(call) == D("71.50")
    again = await dispatch("marcar_gasto_devuelto", {"socio": "Socio A"}, SessionLocal, SPEAKER)
    assert again.is_error
    assert "No hay gastos pendientes de devolver a Socio A" in again.content
