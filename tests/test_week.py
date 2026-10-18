"""The full week of cuaderno Part 9, reproduced through the services."""

from datetime import date
from decimal import Decimal as D

import pytest

from app.domain.types import BoxStatus, PaymentMethod
from app.services import (
    boxes,
    expenses,
    inventory,
    purchases,
    rates,
    sales,
    settlements,
)
from app.services.settlements import SettlementInput
from tests.conftest import Call

RATES = {
    date(2026, 10, 11): D("876.20"),
    date(2026, 10, 12): D("876.80"),
    date(2026, 10, 13): D("877.30"),
    date(2026, 10, 14): D("877.90"),
    date(2026, 10, 15): D("878.40"),
    date(2026, 10, 16): D("879.00"),
    # The notebook gives no rate for the closing day; any value works for the checks.
    date(2026, 10, 18): D("880.00"),
}

DAILY_SALES = [
    (date(2026, 10, 12), 3, 0, 4, PaymentMethod.MOBILE_PAYMENT, 94, D("19.59"), D("17176.51")),
    (date(2026, 10, 13), 2, 1, 2, PaymentMethod.CASH_USD, 77, D("16.07"), D("14098.21")),
    (date(2026, 10, 14), 3, 0, 3, PaymentMethod.CARD, 93, D("19.38"), D("17013.70")),
    (date(2026, 10, 15), 2, 0, 3, PaymentMethod.MOBILE_PAYMENT, 63, D("13.13"), D("11533.39")),
    (date(2026, 10, 16), 1, 0, 0, PaymentMethod.CASH_BS, 30, D("6.25"), D("5493.75")),
]


async def _live_the_week(call: Call) -> dict[str, object]:
    for day, rate in RATES.items():
        await call(rates.set_rate, rates.SetRateInput(day=day, rate=rate))
    seen: dict[str, object] = {}
    seen["box1"] = await call(
        purchases.register_purchase,
        purchases.PurchaseInput(
            day=date(2026, 10, 11),
            box_count=1,
            cost_per_box_usd=D("60.00"),
            payment_method=PaymentMethod.CASH_USD,
            supplier="Granja X",
        ),
    )
    seen["bags"] = await call(
        expenses.record_expense,
        expenses.ExpenseInput(
            day=date(2026, 10, 12), concept="Bolsas plásticas", amount_usd=D("0.40")
        ),
    )
    sold = []
    for day, cartons, halves, units, method, *_ in DAILY_SALES:
        if day == date(2026, 10, 15):
            seen["box2"] = await call(
                purchases.register_purchase,
                purchases.PurchaseInput(
                    day=day,
                    box_count=1,
                    cost_per_box_usd=D("63.00"),
                    payment_method=PaymentMethod.CASH_USD,
                    supplier="Granja X",
                ),
            )
            seen["transport"] = await call(
                expenses.record_expense,
                expenses.ExpenseInput(
                    day=day,
                    concept="Transporte (ida a buscar la caja)",
                    amount_usd=D("1.50"),
                    paid_by_partner="Socio A",
                ),
            )
        sold.append(
            await call(
                sales.record_sale,
                sales.SaleInput(
                    day=day, cartons=cartons, halves=halves, units=units, payment_method=method
                ),
            )
        )
        if day == date(2026, 10, 14):
            await call(inventory.record_loss, inventory.LossInput(day=day, kind="broken", eggs=3))
    seen["sales"] = sold
    return seen


@pytest.mark.usefixtures("two_partners")
async def test_part9_week_reproduces_every_number(call: Call) -> None:
    seen = await _live_the_week(call)

    box1 = seen["box1"]
    assert isinstance(box1, purchases.RegisteredPurchase)
    assert (box1.total_usd, box1.rate, box1.total_bs) == (D("60.00"), D("876.20"), D("52572.00"))
    assert (box1.boxes[0].number, box1.boxes[0].carton_price) == (1, D("6.25"))
    assert (box1.boxes[0].half_price, box1.boxes[0].unit_price) == (D("3.15"), D("0.21"))
    assert box1.price_notice is None

    box2 = seen["box2"]
    assert isinstance(box2, purchases.RegisteredPurchase)
    assert (box2.total_usd, box2.rate, box2.total_bs) == (D("63.00"), D("878.40"), D("55339.20"))
    assert box2.boxes[0].number == 2
    assert [box2.boxes[0].box_price, box2.boxes[0].carton_price] == [D("78.75"), D("6.60")]
    assert [box2.boxes[0].half_price, box2.boxes[0].unit_price] == [D("3.30"), D("0.22")]
    assert box2.price_notice is not None
    assert "Caja 1" in box2.price_notice

    transport = seen["transport"]
    assert isinstance(transport, expenses.ExpenseView)
    assert (transport.rate, transport.amount_bs) == (D("878.40"), D("1317.60"))

    for sale, (day, *_, eggs, usd, bs) in zip(seen["sales"], DAILY_SALES, strict=True):  # type: ignore[call-overload]
        assert (sale.day, sale.eggs, sale.amount_usd, sale.amount_bs) == (day, eggs, usd, bs)
        assert [part.box_number for part in sale.parts] == [1]
    assert seen["sales"][-1].finished_boxes == [1]  # type: ignore[index]

    sheet = await call(boxes.box_sheet, 1)
    assert [row.eggs for row in sheet.rows] == [94, 77, 96, 63, 30]
    assert [row.amount_usd for row in sheet.rows] == [usd for *_, usd, _ in DAILY_SALES]
    assert [row.amount_bs for row in sheet.rows] == [bs for *_, bs in DAILY_SALES]
    assert [row.rate for row in sheet.rows] == [RATES[day] for day, *_ in DAILY_SALES]
    assert (sum(r.cartons for r in sheet.rows), sum(r.halves for r in sheet.rows)) == (11, 1)
    assert (sum(r.units for r in sheet.rows), sheet.total_broken) == (12, 3)
    assert (sheet.total_eggs, sheet.total_sales_usd) == (360, D("74.42"))
    assert sheet.box.status == BoxStatus.FINISHED
    assert sheet.box.finished_on == date(2026, 10, 16)

    profit = await call(boxes.box_profit, 1)
    assert profit.model_dump() == {
        "number": 1,
        "cost_usd": D("60.00"),
        "next_box_number": 2,
        "next_box_cost_usd": D("63.00"),
        "difference_usd": D("3.00"),
        "final_cost_usd": D("63.00"),
        "sales_usd": D("74.42"),
        "profit_usd": D("11.42"),
        "broken_eggs": 3,
        "broken_loss_usd": D("0.50"),
        "broken_percent": D("0.8"),
    }

    ledger = await call(inventory.stock_ledger, date(2026, 10, 11), date(2026, 10, 16))
    assert [
        (r.day.day, r.entered, r.sold, r.broken, r.remaining_eggs, r.remaining_boxes)
        for r in ledger
    ] == [
        (11, 360, 0, 0, 360, D("1.00")),
        (12, 0, 94, 0, 266, D("0.74")),
        (13, 0, 77, 0, 189, D("0.53")),
        (14, 0, 93, 3, 93, D("0.26")),
        (15, 360, 63, 0, 390, D("1.08")),
        (16, 0, 30, 0, 360, D("1.00")),
    ]
    assert [ledger[0].description, ledger[4].description] == [
        "Compra caja 1",
        "Ventas + compra caja 2",
    ]

    stock = await call(inventory.stock)
    assert (stock.total_eggs, [b.number for b in stock.boxes]) == (360, [2])
    assert stock.boxes[0].status == BoxStatus.STOCKED

    closing = SettlementInput(day=date(2026, 10, 18))
    preview = await call(settlements.preview_settlement, closing)
    assert [b.number for b in preview.boxes] == [1]
    assert (preview.box_profit_usd, preview.expenses_usd) == (D("11.42"), D("1.90"))
    assert (preview.reserve_usd, preview.net_profit_usd) == (D("0.00"), D("9.52"))
    assert [(s.partner, s.amount_usd) for s in preview.shares] == [
        ("Socio A", D("5.71")),
        ("Socio B", D("3.81")),
    ]
    assert preview.shares_total_usd == preview.net_profit_usd
    assert preview.next_box_money_usd == D("63.00")
    assert [(r.partner, r.amount_usd) for r in preview.reimbursements] == [("Socio A", D("1.50"))]
    assert preview.sales_usd - preview.next_box_money_usd - preview.expenses_usd == D("9.52")

    done = await call(settlements.execute_settlement, closing)
    assert done.model_dump(exclude={"id"}) == preview.model_dump()
    assert (await call(boxes.box_sheet, 1)).box.status == BoxStatus.SETTLED
    assert await call(expenses.pending) == []
    with pytest.raises(Exception, match="No hay nada que cerrar"):
        await call(settlements.preview_settlement, closing)
    stored = (await call(settlements.list_settlements))[0]
    assert (stored.net_profit_usd, stored.shares) == (done.net_profit_usd, done.shares)
    assert [b.number for b in stored.boxes] == [1]
    assert [(e.concept, e.reimbursed_on, e.settled) for e in stored.expenses] == [
        ("Bolsas plásticas", None, True),
        ("Transporte (ida a buscar la caja)", date(2026, 10, 18), True),
    ]
