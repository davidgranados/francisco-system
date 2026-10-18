from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

INVENTORY_LOCK_KEY = 4_206_201


async def session_scope() -> AsyncIterator[AsyncSession]:
    """One transaction per request: commit on success, roll back on any exception."""
    async with SessionLocal() as session, session.begin():
        yield session


async def lock_inventory(session: AsyncSession) -> None:
    """Serialize every write that moves eggs or money between boxes, for this transaction."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": INVENTORY_LOCK_KEY})
