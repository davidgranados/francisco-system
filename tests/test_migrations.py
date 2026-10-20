"""Data migrations, run against a database of their own at the revision before them."""

import asyncio
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal as D

import asyncpg
import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command
from app.config import settings
from tests.conftest import TEST_DATABASE_URL

URL = make_url(TEST_DATABASE_URL.replace("francisco_test", "francisco_migration_test"))


def _migrate(direction: str, revision: str) -> None:
    previous = settings.database_url
    settings.database_url = URL.render_as_string(hide_password=False)
    try:
        config = Config("alembic.ini")
        config.attributes["configure_logger"] = False
        getattr(command, direction)(config, revision)
    finally:
        settings.database_url = previous


async def _connect(database: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=URL.host, port=URL.port, user=URL.username, password=URL.password, database=database
    )


@pytest.fixture
async def db() -> AsyncIterator[asyncpg.Connection]:
    admin = await _connect("postgres")
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{URL.database}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{URL.database}"')
        assert URL.database
        connection = await _connect(URL.database)
        try:
            yield connection
        finally:
            await connection.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{URL.database}" WITH (FORCE)')
    finally:
        await admin.close()


async def test_a_purchase_a_partner_paid_becomes_their_contribution(
    db: asyncpg.Connection,
) -> None:
    await asyncio.to_thread(_migrate, "upgrade", "7c1d4e8a2f60")
    partner = await db.fetchval(
        "INSERT INTO partners (name, share) VALUES ('Daniel', 1) RETURNING id"
    )
    purchase = (
        "INSERT INTO purchases (day, box_count, cost_per_box_usd, rate, total_usd, total_bs, "
        "payment_method, paid_by_partner_id, voided) "
        "VALUES ($1, 1, 63, 878.4, 63, 55339.2, 'pago_movil', $2, $3) RETURNING id"
    )
    paid = await db.fetchval(purchase, date(2026, 10, 15), partner, False)
    await db.fetchval(purchase, date(2026, 10, 16), partner, True)
    await db.fetchval(purchase, date(2026, 10, 17), None, False)

    await asyncio.to_thread(_migrate, "upgrade", "head")

    rows = await db.fetch("SELECT partner_id, day, amount_usd, note FROM contributions")
    assert [tuple(row) for row in rows] == [
        (
            partner,
            date(2026, 10, 15),
            D("63.00"),
            f"Compra {paid} pagada por el socio, pasada a aporte",
        )
    ]
    columns = await db.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'purchases'"
    )
    assert "paid_by_partner_id" not in {row["column_name"] for row in columns}

    await asyncio.to_thread(_migrate, "downgrade", "7c1d4e8a2f60")

    assert await db.fetchval("SELECT count(*) FROM contributions") == 0
    assert await db.fetchval("SELECT paid_by_partner_id FROM purchases WHERE id = $1", paid) == (
        partner
    )


async def test_a_partner_expense_given_back_on_its_cierre_day_is_marked_paid_by_the_cierre(
    db: asyncpg.Connection,
) -> None:
    await asyncio.to_thread(_migrate, "upgrade", "3e5b9a7c4d12")
    partner = await db.fetchval(
        "INSERT INTO partners (name, share) VALUES ('Daniel', 1) RETURNING id"
    )
    settlement = await db.fetchval(
        "INSERT INTO settlements (day, box_profit_usd, expenses_usd, reserve_usd, "
        "net_profit_usd, rate, amount_bs, next_box_money_usd) "
        "VALUES ('2026-10-18', 0, 3, 0, -3, 880, 0, 0) RETURNING id"
    )
    expense = (
        "INSERT INTO expenses (day, concept, amount_usd, rate, amount_bs, paid_by_partner_id, "
        "reimbursed_on, settlement_id) VALUES ('2026-10-15', $1, 1, 880, 880, $2, $3, $4) "
        "RETURNING id"
    )
    by_cierre = await db.fetchval(expense, "Transporte", partner, date(2026, 10, 18), settlement)
    by_hand = await db.fetchval(expense, "Bolsas", partner, date(2026, 10, 16), settlement)
    business = await db.fetchval(expense, "Agua", None, None, settlement)

    await asyncio.to_thread(_migrate, "upgrade", "head")

    rows = await db.fetch("SELECT id, reimbursed_by_settlement FROM expenses ORDER BY id")
    assert [tuple(row) for row in rows] == [(by_cierre, True), (by_hand, False), (business, False)]

    await asyncio.to_thread(_migrate, "downgrade", "3e5b9a7c4d12")

    columns = await db.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'expenses'"
    )
    assert "reimbursed_by_settlement" not in {row["column_name"] for row in columns}
