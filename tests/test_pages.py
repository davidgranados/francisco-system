from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal as D

import httpx
import pytest

from app.main import app
from app.services import expenses, rates
from tests.conftest import Call

KEY = {"X-API-Key": "clave-de-prueba"}


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _rates(call: Call, days: int) -> None:
    for day in range(1, days + 1):
        await call(rates.set_rate, rates.SetRateInput(day=date(2026, 9, day), rate=D(100 + day)))


async def test_a_page_has_its_slice_newest_first_and_the_real_total(
    client: httpx.AsyncClient, call: Call
) -> None:
    await _rates(call, 5)
    response = await client.get("/api/v1/rates?page=2&page_size=2", headers=KEY)
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"day": "2026-09-03", "rate": "103.0000", "source": "manual"},
            {"day": "2026-09-02", "rate": "102.0000", "source": "manual"},
        ],
        "total": 5,
        "page": 2,
        "page_size": 2,
    }


async def test_a_page_past_the_end_is_empty_with_the_real_total(
    client: httpx.AsyncClient, call: Call
) -> None:
    await _rates(call, 3)
    response = await client.get("/api/v1/rates?page=9", headers=KEY)
    assert response.json() == {"items": [], "total": 3, "page": 9, "page_size": 20}


@pytest.mark.parametrize("query", ["page=0", "page_size=0", "page_size=101"])
async def test_a_page_out_of_range_is_refused(client: httpx.AsyncClient, query: str) -> None:
    response = await client.get(f"/api/v1/rates?{query}", headers=KEY)
    assert response.status_code == 422


@pytest.mark.usefixtures("two_partners")
async def test_expenses_list_every_expense_newest_first(
    client: httpx.AsyncClient, call: Call
) -> None:
    await _rates(call, 2)
    for day, concept in ((1, "Bolsas"), (2, "Gasolina")):
        await call(
            expenses.record_expense,
            expenses.ExpenseInput(day=date(2026, 9, day), concept=concept, amount_usd=D("5")),
        )
    page = (await client.get("/api/v1/expenses", headers=KEY)).json()
    assert ([e["concept"] for e in page["items"]], page["total"]) == (["Gasolina", "Bolsas"], 2)


@pytest.mark.usefixtures("capital")
async def test_fund_balances_and_transfers_read_through_the_api(
    client: httpx.AsyncClient,
) -> None:
    balances = await client.get("/api/v1/funds/balances", headers=KEY)
    assert balances.json()["capital_usd"] == "10000.00"
    transfers = await client.get("/api/v1/transfers", headers=KEY)
    assert transfers.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}
    assert (await client.post("/api/v1/transfers", json={}, headers=KEY)).status_code == 405


@pytest.mark.usefixtures("capital")
async def test_the_ledger_lists_page_what_was_recorded(client: httpx.AsyncClient) -> None:
    await client.put("/api/v1/rates", json={"day": "2026-10-12", "rate": "876.80"}, headers=KEY)
    purchase = {
        "day": "2026-10-12",
        "box_count": 2,
        "cost_per_box_usd": "60.00",
        "payment_method": "efectivo_usd",
    }
    assert (await client.post("/api/v1/purchases", json=purchase, headers=KEY)).status_code == 201
    sale = {"day": "2026-10-12", "cartons": 1, "payment_method": "punto"}
    assert (await client.post("/api/v1/sales", json=sale, headers=KEY)).status_code == 201

    async def page(path: str) -> dict:
        response = await client.get(path, headers=KEY)
        assert response.status_code == 200, response.text
        return response.json()

    assert (await page("/api/v1/purchases"))["total"] == 1
    assert [b["number"] for b in (await page("/api/v1/boxes"))["items"]] == [2, 1]
    assert (await page("/api/v1/sales"))["total"] == 1
    assert (await page("/api/v1/sales?day=2026-10-11"))["total"] == 0
    assert [c["amount_usd"] for c in (await page("/api/v1/contributions"))["items"]] == ["10000.00"]
    assert (await page("/api/v1/settlements"))["items"] == []
