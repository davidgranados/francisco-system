from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.config import today
from app.domain.errors import DomainError
from app.domain.types import BoxStatus, PaymentMethod, RateSource
from app.services import (
    boxes,
    contributions,
    expenses,
    inventory,
    partners,
    pricing,
    purchases,
    rates,
    reports,
    sales,
    settlements,
)
from tests.conftest import Call

DAY = date(2026, 10, 14)


async def _rate(call: Call, day: date = DAY, rate: str = "877.90") -> None:
    await call(rates.set_rate, rates.SetRateInput(day=day, rate=D(rate)))


async def _buy(
    call: Call, cost: str, count: int = 1, day: date = DAY
) -> purchases.RegisteredPurchase:
    return await call(
        purchases.register_purchase,
        purchases.PurchaseInput(
            day=day,
            box_count=count,
            cost_per_box_usd=D(cost),
            payment_method=PaymentMethod.CASH_USD,
        ),
    )


async def _sell(
    call: Call, cartons: int = 0, halves: int = 0, units: int = 0, **extra: object
) -> sales.RegisteredSale:
    return await call(
        sales.record_sale,
        sales.SaleInput(
            day=DAY,
            cartons=cartons,
            halves=halves,
            units=units,
            payment_method=PaymentMethod.CASH_USD,
            **extra,
        ),
    )


@pytest.mark.usefixtures("capital")
async def test_plantilla_a_price_list_of_the_day(call: Call) -> None:
    await _rate(call)
    await _buy(call, "60.00")
    prices = await call(pricing.price_list, DAY)
    assert [
        (line.usd, line.bs) for line in (prices.box, prices.carton, prices.half, prices.unit)
    ] == [
        (D("75.00"), D("65842.50")),
        (D("6.25"), D("5486.88")),
        (D("3.15"), D("2765.39")),
        (D("0.21"), D("184.36")),
    ]


@pytest.mark.usefixtures("capital")
async def test_a_sale_crossing_two_boxes_splits_eggs_and_money(call: Call) -> None:
    await _rate(call)
    await _buy(call, "60.00")
    await _buy(call, "63.00")
    before = await _sell(call, cartons=11)

    crossing = await _sell(call, cartons=1, units=1)

    assert crossing.amount_usd == D("6.46")
    assert [(p.box_number, p.eggs, p.amount_usd) for p in crossing.parts] == [
        (1, 30, D("6.25")),
        (2, 1, D("0.21")),
    ]
    assert crossing.finished_boxes == [1]
    assert crossing.eggs_left == 359
    first, second = await call(boxes.box_sheet, 1), await call(boxes.box_sheet, 2)
    assert (first.box.status, first.total_eggs, first.total_sales_usd) == (
        BoxStatus.FINISHED,
        360,
        D("75.00"),
    )
    assert (second.box.status, second.rows[0].shared_sale_eggs, second.rows[0].amount_usd) == (
        BoxStatus.OPEN,
        1,
        D("0.21"),
    )
    assert second.rows[0].amount_bs == D("184.36")
    assert first.rows[-1].amount_bs == before.amount_bs + crossing.amount_bs - D("184.36")


@pytest.mark.usefixtures("capital")
async def test_a_count_with_missing_eggs_records_shrinkage_on_the_open_box(call: Call) -> None:
    await _rate(call)
    await _buy(call, "60.00", count=2)
    await _sell(call, cartons=3, units=4)

    count = await call(inventory.record_count, inventory.CountInput(day=DAY, counted_eggs=620))

    assert (count.expected_eggs, count.difference, count.shrinkage_parts) == (626, -6, [(1, 6)])
    stock = await call(inventory.stock)
    assert stock.total_eggs == 620
    assert [b.remaining_eggs for b in stock.boxes] == [260, 360]
    ledger = await call(inventory.stock_ledger, DAY, DAY)
    assert (ledger[0].other_losses, ledger[0].counted, ledger[0].difference) == (6, 620, -6)


@pytest.mark.usefixtures("capital")
async def test_a_count_with_extra_eggs_changes_nothing_and_warns(call: Call) -> None:
    await _rate(call)
    await _buy(call, "60.00")
    count = await call(inventory.record_count, inventory.CountInput(day=DAY, counted_eggs=365))
    assert (count.difference, count.shrinkage_parts) == (5, [])
    assert count.notice is not None
    assert (await call(inventory.stock)).total_eggs == 360


@pytest.mark.usefixtures("capital")
async def test_settlement_with_no_boxes_covers_expenses_and_shares_nothing(call: Call) -> None:
    await _rate(call)
    await _buy(call, "60.00")
    await _sell(call, cartons=1)
    await call(
        expenses.record_expense,
        expenses.ExpenseInput(
            day=DAY, concept="Transporte", amount_usd=D("1.50"), paid_by_partner="Socio A"
        ),
    )
    await call(
        expenses.record_expense,
        expenses.ExpenseInput(day=DAY, concept="Bolsas", amount_usd=D("0.40")),
    )

    done = await call(settlements.execute_settlement, settlements.SettlementInput(day=DAY))

    assert (done.boxes, done.box_profit_usd, done.expenses_usd) == ([], D("0.00"), D("1.90"))
    assert done.net_profit_usd == D("-1.90")
    assert [s.amount_usd for s in done.shares] == [D("0.00"), D("0.00")]
    assert done.amount_bs == D("0.00")
    assert await call(expenses.pending) == []


@pytest.mark.usefixtures("capital")
async def test_settlement_reserve_as_percent_comes_off_before_the_split(call: Call) -> None:
    await _rate(call)
    await _buy(call, "60.00")
    await _buy(call, "63.00")
    await _sell(call, cartons=12)
    preview = await call(
        settlements.preview_settlement,
        settlements.SettlementInput(day=DAY, reserve_percent=D("0.10")),
    )
    assert (preview.box_profit_usd, preview.reserve_usd, preview.net_profit_usd) == (
        D("12.00"),
        D("1.20"),
        D("10.80"),
    )
    assert [s.amount_usd for s in preview.shares] == [D("6.48"), D("4.32")]


@pytest.mark.usefixtures("capital")
async def test_a_box_without_its_next_box_has_no_profit_yet(call: Call) -> None:
    await _rate(call)
    await _buy(call, "60.00")
    await _sell(call, cartons=12)
    with pytest.raises(DomainError, match="Todavía no se compró la Caja 2"):
        await call(boxes.box_profit, 1)
    assert (await call(boxes.box_sheet, 1)).profit is None


@pytest.mark.usefixtures("capital")
async def test_a_sale_needs_eggs(call: Call) -> None:
    await _rate(call)
    with pytest.raises(DomainError, match="No hay huevos"):
        await _sell(call, cartons=1)
    await _buy(call, "60.00")
    with pytest.raises(DomainError, match="quedan 360 huevos"):
        await _sell(call, cartons=13)


async def test_an_expense_paid_in_bolivares_is_converted_at_the_day_rate(call: Call) -> None:
    await _rate(call)
    expense = await call(
        expenses.record_expense,
        expenses.ExpenseInput(day=DAY, concept="Transporte", amount_bs=D("1316.85")),
    )
    assert (expense.amount_usd, expense.amount_bs) == (D("1.50"), D("1316.85"))
    with pytest.raises(ValueError, match="uno de los dos"):
        expenses.ExpenseInput(concept="Bolsas")


@pytest.mark.usefixtures("capital")
async def test_a_whole_box_sale_uses_the_box_price_and_empties_the_box(call: Call) -> None:
    await _rate(call)
    await _buy(call, "63.00")
    sale = await _sell(call, boxes=1)
    assert (sale.eggs, sale.amount_usd, sale.finished_boxes, sale.eggs_left) == (
        360,
        D("78.75"),
        [1],
        0,
    )
    sheet = await call(boxes.box_sheet, 1)
    assert ([row.boxes for row in sheet.rows], sheet.total_eggs) == ([1], 360)


@pytest.mark.usefixtures("capital")
async def test_part6_payment_in_bolivares_is_converted_at_the_day_rate(call: Call) -> None:
    await _rate(call)
    await _buy(call, "60.00")
    sale = await _sell(call, cartons=4, charged_bs=D("21947.50"))
    assert (sale.list_amount_usd, sale.amount_usd, sale.amount_bs) == (
        D("25.00"),
        D("25.00"),
        D("21947.50"),
    )


@pytest.mark.usefixtures("capital")
async def test_voiding_a_sale_gives_the_eggs_back(call: Call) -> None:
    await _rate(call)
    await _buy(call, "60.00")
    await _buy(call, "63.00")
    sale = await _sell(call, cartons=12, units=1)
    assert (await call(boxes.box_sheet, 1)).box.status == BoxStatus.FINISHED

    voided = await call(sales.void_sale, sale.id, purchases.VoidInput(reason="error"))

    assert voided.voided
    stock = await call(inventory.stock)
    assert stock.total_eggs == 720
    assert [b.status for b in stock.boxes] == [BoxStatus.STOCKED, BoxStatus.STOCKED]
    with pytest.raises(DomainError, match="ya estaba anulada"):
        await call(sales.void_sale, sale.id, purchases.VoidInput(reason="otra vez"))


@pytest.mark.usefixtures("capital")
async def test_voiding_refuses_to_leave_two_open_boxes(call: Call) -> None:
    await _rate(call)
    await _buy(call, "60.00")
    await _buy(call, "63.00")
    first = await _sell(call, cartons=12)
    await _sell(call, cartons=1)
    with pytest.raises(DomainError, match="ya se siguió vendiendo"):
        await call(sales.void_sale, first.id, purchases.VoidInput(reason="error"))
    assert (await call(inventory.stock)).total_eggs == 330


@pytest.mark.usefixtures("capital")
async def test_a_settled_sale_cannot_be_voided(call: Call) -> None:
    await _rate(call)
    await _buy(call, "60.00")
    await _buy(call, "63.00")
    sale = await _sell(call, cartons=12)
    await call(settlements.execute_settlement, settlements.SettlementInput(day=DAY))
    with pytest.raises(DomainError, match="ya entró en un cierre"):
        await call(sales.void_sale, sale.id, purchases.VoidInput(reason="error"))


@pytest.mark.usefixtures("capital")
async def test_voiding_an_untouched_purchase_renumbers_later_boxes(call: Call) -> None:
    await _rate(call)
    await _buy(call, "60.00")
    wrong = await _buy(call, "63.00", count=2)
    await _buy(call, "64.00")
    await _sell(call, cartons=1)

    await call(purchases.void_purchase, wrong.id, purchases.VoidInput(reason="duplicada"))

    numbers = [(b.number, b.cost_usd) for b in await call(boxes.list_boxes)]
    assert numbers == [(1, D("60.00")), (2, D("64.00"))]
    first = (await call(purchases.list_purchases))[-1]
    with pytest.raises(DomainError, match="caja 1"):
        await call(purchases.void_purchase, first.id, purchases.VoidInput(reason="x"))


@pytest.mark.usefixtures("capital")
async def test_adjusting_prices_of_the_open_box_from_the_new_cost(call: Call) -> None:
    await _rate(call)
    await _buy(call, "60.00")
    await _sell(call, cartons=1)
    await _buy(call, "63.00")
    adjusted = await call(
        pricing.adjust_prices, pricing.AdjustPricesInput(base_cost_usd=D("63.00"))
    )
    assert (adjusted.number, adjusted.carton_price, adjusted.unit_price) == (
        1,
        D("6.60"),
        D("0.22"),
    )
    assert (await _sell(call, cartons=1)).amount_usd == D("6.60")


async def test_rate_of_a_past_day_falls_back_to_the_last_stored(call: Call) -> None:
    await _rate(call, DAY, "877.90")
    later = await call(rates.rate_for, DAY + timedelta(days=2))
    assert (later.rate, later.rate_day, later.stale) == (D("877.9000"), DAY, True)
    with pytest.raises(DomainError, match="Dígame la tasa"):
        await call(rates.rate_for, DAY - timedelta(days=1))


async def test_todays_rate_is_fetched_once_and_stored(
    call: Call, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    async def fetch() -> D:
        calls.append(1)
        return D("880.1159")

    monkeypatch.setattr(rates, "fetch_bcv_rate", fetch)
    first = await call(rates.rate_for, today())
    second = await call(rates.rate_for, today())
    assert (first.rate, first.source, first.stale) == (D("880.1159"), RateSource.BCV_API, False)
    assert second == first
    assert calls == [1]


async def test_todays_rate_falls_back_when_the_api_fails(
    call: Call, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail() -> D:
        raise rates.RateUnavailable("down")

    monkeypatch.setattr(rates, "fetch_bcv_rate", fail)
    await _rate(call, today() - timedelta(days=1), "879.00")
    rate = await call(rates.rate_for, today())
    assert (rate.rate, rate.stale) == (D("879.0000"), True)


async def test_partner_seed_is_idempotent(call: Call) -> None:
    entries = [
        partners.PartnerEntry(name="Ana", share=D("0.60"), telegram_user_id=1),
        partners.PartnerEntry(name="Beto", share=D("0.40")),
    ]
    first = await call(partners.replace_partners, entries)
    second = await call(partners.replace_partners, entries)
    assert first == second
    assert [(p.name, p.share) for p in second] == [("Ana", D("0.6000")), ("Beto", D("0.4000"))]
    with pytest.raises(DomainError, match="sumar 1"):
        await call(partners.replace_partners, entries[:1])


@pytest.mark.usefixtures("two_partners")
async def test_contributions_stay_out_of_profit_and_count_as_money_in(call: Call) -> None:
    await _rate(call)
    await call(
        contributions.record_contribution,
        contributions.ContributionInput(partner="Socio B", amount_usd=D("100.00"), day=DAY),
    )
    await _buy(call, "60.00")
    await _sell(call, cartons=2)
    summary = await call(reports.summary, reports.PeriodInput(date_from=DAY, date_to=DAY))
    assert (summary.sales_usd, summary.eggs_sold, summary.purchases_usd) == (
        D("12.50"),
        60,
        D("60.00"),
    )
    assert summary.sales_by_payment_method == {PaymentMethod.CASH_USD: D("12.50")}
    assert (summary.cash.capital.entered_usd, summary.cash.capital.left_usd) == (
        D("100.00"),
        D("60.00"),
    )
    assert (summary.cash.capital.closing_usd, summary.cash.petty_cash.closing_usd) == (
        D("40.00"),
        D("12.50"),
    )
