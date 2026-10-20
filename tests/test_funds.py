"""Capital, caja chica and caja de ahorros, seen through the services that move money."""

from datetime import date
from decimal import Decimal as D

import pytest

from app.domain.errors import DomainError
from app.domain.types import PaymentMethod
from app.services import (
    contributions,
    expenses,
    funds,
    purchases,
    rates,
    reports,
    sales,
    settlements,
)
from tests.conftest import Call

DAY = date(2026, 10, 14)


async def _contribute(call: Call, partner: str, amount: str, day: date = DAY) -> None:
    await call(
        contributions.record_contribution,
        contributions.ContributionInput(partner=partner, amount_usd=D(amount), day=day),
    )


def _purchase(count: int, cost: str = "60.00") -> purchases.PurchaseInput:
    return purchases.PurchaseInput(
        day=DAY, box_count=count, cost_per_box_usd=D(cost), payment_method=PaymentMethod.CASH_USD
    )


@pytest.fixture(autouse=True)
async def rate(call: Call) -> None:
    await call(rates.set_rate, rates.SetRateInput(day=DAY, rate=D("877.90")))


@pytest.mark.usefixtures("two_partners")
async def test_a_purchase_beyond_the_capital_is_refused_until_an_aporte_covers_it(
    call: Call,
) -> None:
    await _contribute(call, "Socio A", "80.00")

    with pytest.raises(DomainError) as refused:
        await call(purchases.register_purchase, _purchase(2))
    assert refused.value.message == (
        "El capital disponible es $ 80,00 y la compra cuesta $ 120,00. Falta un aporte de "
        "$ 40,00: regístrelo con registrar_aporte y vuelva a registrar la compra."
    )
    assert await call(purchases.list_purchases) == []

    await _contribute(call, "Socio B", "40.00")
    bought = await call(purchases.register_purchase, _purchase(2))

    assert bought.total_usd == D("120.00")
    after = await call(funds.balances)
    assert after.capital_usd == D("0.00")
    assert [(c.partner, c.amount_usd) for c in after.contributed_by_partner] == [
        ("Socio A", D("80.00")),
        ("Socio B", D("40.00")),
    ]


@pytest.mark.usefixtures("two_partners")
async def test_a_voided_purchase_gives_its_money_back_to_the_capital(call: Call) -> None:
    await _contribute(call, "Socio A", "60.00")
    bought = await call(purchases.register_purchase, _purchase(1))
    await call(purchases.void_purchase, bought.id, purchases.VoidInput(reason="repetida"))

    assert (await call(funds.balances)).capital_usd == D("60.00")


@pytest.mark.usefixtures("two_partners")
async def test_sales_fill_the_caja_chica_and_expenses_leave_it_when_the_business_pays(
    call: Call,
) -> None:
    await _contribute(call, "Socio A", "60.00")
    await call(purchases.register_purchase, _purchase(1))
    await call(
        sales.record_sale,
        sales.SaleInput(day=DAY, cartons=2, payment_method=PaymentMethod.CASH_USD),
    )
    await call(
        expenses.record_expense,
        expenses.ExpenseInput(day=DAY, concept="Bolsas", amount_usd=D("0.40")),
    )
    paid_by_partner = await call(
        expenses.record_expense,
        expenses.ExpenseInput(
            day=DAY, concept="Transporte", amount_usd=D("1.50"), paid_by_partner="Socio B"
        ),
    )

    before_reimbursing = await call(funds.balances)
    assert (before_reimbursing.capital_usd, before_reimbursing.petty_cash_usd) == (
        D("0.00"),
        D("12.10"),
    )

    await call(expenses.mark_reimbursed, paid_by_partner.id, expenses.ReimburseInput(day=DAY))

    after = await call(funds.balances)
    assert (after.capital_usd, after.petty_cash_usd, after.savings_usd) == (
        D("0.00"),
        D("10.60"),
        D("0.00"),
    )


@pytest.mark.usefixtures("two_partners")
async def test_the_cash_flow_opens_each_fund_where_the_day_before_closed(call: Call) -> None:
    await _contribute(call, "Socio A", "100.00", day=date(2026, 10, 13))
    await _contribute(call, "Socio B", "20.00")
    await call(purchases.register_purchase, _purchase(1))
    await call(
        sales.record_sale,
        sales.SaleInput(day=DAY, cartons=2, payment_method=PaymentMethod.CASH_USD),
    )

    flow = await call(reports.cash_flow, DAY, DAY)

    assert flow.capital.model_dump() == {
        "opening_usd": D("100.00"),
        "entered_usd": D("20.00"),
        "left_usd": D("60.00"),
        "closing_usd": D("60.00"),
    }
    assert (flow.petty_cash.opening_usd, flow.petty_cash.closing_usd) == (D("0.00"), D("12.50"))
    assert (await call(funds.balances)).capital_usd == flow.capital.closing_usd


async def _week_to_close(call: Call) -> None:
    await _contribute(call, "Socio A", "123.00")
    await call(purchases.register_purchase, _purchase(1, "60.00"))
    await call(purchases.register_purchase, _purchase(1, "63.00"))
    await call(
        sales.record_sale,
        sales.SaleInput(day=DAY, cartons=12, payment_method=PaymentMethod.CASH_USD),
    )
    await call(
        expenses.record_expense,
        expenses.ExpenseInput(day=DAY, concept="Bolsas", amount_usd=D("0.40")),
    )
    await call(
        expenses.record_expense,
        expenses.ExpenseInput(
            day=DAY, concept="Transporte", amount_usd=D("1.50"), paid_by_partner="Socio B"
        ),
    )


@pytest.mark.usefixtures("two_partners")
async def test_a_cierre_returns_capital_reinvests_reserves_and_pays_out_the_rest(
    call: Call,
) -> None:
    await _week_to_close(call)
    closing = settlements.SettlementInput(
        day=DAY, reserve_percent=D("0.10"), reinvest_usd=D("2.00")
    )

    preview = await call(settlements.preview_settlement, closing)

    assert (preview.box_profit_usd, preview.expenses_usd) == (D("12.00"), D("1.90"))
    assert (preview.next_box_money_usd, preview.reinvest_usd) == (D("63.00"), D("2.00"))
    assert (preview.reserve_usd, preview.net_profit_usd) == (D("1.01"), D("7.09"))
    assert [(s.partner, s.amount_usd) for s in preview.shares] == [
        ("Socio A", D("4.25")),
        ("Socio B", D("2.84")),
    ]
    assert (preview.capital_after_usd, preview.savings_after_usd) == (D("65.00"), D("1.01"))
    assert preview.petty_cash_after_usd == D("0.00")

    await call(settlements.execute_settlement, closing)

    after = await call(funds.balances)
    assert (after.capital_usd, after.petty_cash_usd, after.savings_usd) == (
        D("65.00"),
        D("0.00"),
        D("1.01"),
    )
    stored = (await call(settlements.list_settlements))[0]
    money = {"reinvest_usd", "capital_after_usd", "petty_cash_after_usd", "savings_after_usd"}
    assert stored.model_dump(include=money) == preview.model_dump(include=money)


@pytest.mark.usefixtures("two_partners")
async def test_a_percent_reinvestment_uses_the_same_base_as_the_reserve(call: Call) -> None:
    await _week_to_close(call)

    preview = await call(
        settlements.preview_settlement,
        settlements.SettlementInput(day=DAY, reserve_percent=D("0.10"), reinvest_percent=D("0.50")),
    )

    assert (preview.reserve_usd, preview.reinvest_usd, preview.net_profit_usd) == (
        D("1.01"),
        D("5.05"),
        D("4.04"),
    )


@pytest.mark.usefixtures("two_partners")
async def test_reserve_and_reinvestment_cannot_take_more_than_the_profit(call: Call) -> None:
    await _week_to_close(call)

    with pytest.raises(DomainError, match="Bájelas"):
        await call(
            settlements.preview_settlement,
            settlements.SettlementInput(day=DAY, reserve_usd=D("5.00"), reinvest_usd=D("5.11")),
        )
    exact = await call(
        settlements.preview_settlement,
        settlements.SettlementInput(day=DAY, reserve_usd=D("5.00"), reinvest_usd=D("5.10")),
    )
    assert exact.net_profit_usd == D("0.00")


@pytest.mark.usefixtures("two_partners")
async def test_percents_that_add_up_to_the_whole_profit_split_it_exactly(call: Call) -> None:
    await _week_to_close(call)

    preview = await call(
        settlements.preview_settlement,
        settlements.SettlementInput(day=DAY, reserve_percent=D("0.25"), reinvest_percent=D("0.75")),
    )

    assert (preview.reserve_usd, preview.reinvest_usd, preview.net_profit_usd) == (
        D("2.53"),
        D("7.57"),
        D("0.00"),
    )
