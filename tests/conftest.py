import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Any

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://francisco:francisco@localhost:5432/francisco_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["API_KEYS"] = "prueba:clave-de-prueba"
for variable in (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET",
    "PUBLIC_URL",
    "RAILWAY_PUBLIC_DOMAIN",
    "ANTHROPIC_API_KEY",
):
    os.environ[variable] = ""

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from alembic import command  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import contributions, partners, rates  # noqa: E402

Call = Callable[..., Awaitable[Any]]


async def _recreate_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    admin = await asyncpg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        database="postgres",
    )
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await admin.close()


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(_recreate_database())
    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")


@pytest.fixture(autouse=True)
async def clean_tables() -> AsyncIterator[None]:
    yield
    names = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def no_network_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse() -> Decimal:
        raise RuntimeError("the BCV API must not be called from tests")

    monkeypatch.setattr(rates, "fetch_bcv_rate", refuse)


@pytest.fixture
def call() -> Call:
    """Run one service call in its own transaction, the way a request or a tool call does."""

    async def run(service: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        async with SessionLocal() as session, session.begin():
            return await service(session, *args, **kwargs)

    return run


@pytest.fixture
async def two_partners(call: Call) -> None:
    await call(
        partners.replace_partners,
        [
            partners.PartnerEntry(name="Socio A", share=Decimal("0.60"), telegram_user_id=111),
            partners.PartnerEntry(name="Socio B", share=Decimal("0.40"), telegram_user_id=222),
        ],
    )


@pytest.fixture
async def capital(call: Call, two_partners: None) -> None:
    """Enough capital that purchases are never refused for money."""
    await call(
        contributions.record_contribution,
        contributions.ContributionInput(
            partner="Socio A", amount_usd=Decimal("10000.00"), day=date(2026, 1, 1)
        ),
    )
