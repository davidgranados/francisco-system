from collections.abc import AsyncIterator

import httpx
import pytest

from app.main import app

KEY = {"X-API-Key": "clave-de-prueba"}


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_healthz_needs_no_key(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "otra"}, {"X-API-Key": ""}])
async def test_api_rejects_missing_or_bad_keys(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/inventory/stock", headers=headers)
    assert response.status_code == 401


@pytest.mark.usefixtures("capital")
async def test_a_purchase_and_a_sale_through_the_api(client: httpx.AsyncClient) -> None:
    assert (
        await client.put("/api/v1/rates", json={"day": "2026-10-12", "rate": "876.80"}, headers=KEY)
    ).status_code == 200
    purchase = await client.post(
        "/api/v1/purchases",
        json={
            "day": "2026-10-12",
            "box_count": 1,
            "cost_per_box_usd": "60.00",
            "payment_method": "efectivo_usd",
        },
        headers=KEY,
    )
    assert purchase.status_code == 201
    sale = await client.post(
        "/api/v1/sales",
        json={"day": "2026-10-12", "cartons": 3, "units": 4, "payment_method": "pago_movil"},
        headers=KEY,
    )
    assert sale.status_code == 201
    assert (sale.json()["amount_usd"], sale.json()["amount_bs"]) == ("19.59", "17176.51")
    stock = await client.get("/api/v1/inventory/stock", headers=KEY)
    assert stock.json()["total_eggs"] == 266


async def test_a_business_refusal_is_a_422_in_spanish_and_writes_nothing(
    client: httpx.AsyncClient,
) -> None:
    await client.put("/api/v1/rates", json={"day": "2026-10-12", "rate": "876.80"}, headers=KEY)
    response = await client.post(
        "/api/v1/sales",
        json={"day": "2026-10-12", "cartons": 1, "payment_method": "punto"},
        headers=KEY,
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": "No hay huevos en existencia. Primero registre una compra."
    }
    sales = await client.get("/api/v1/sales?day=2026-10-12", headers=KEY)
    assert (sales.json()["items"], sales.json()["total"]) == ([], 0)
