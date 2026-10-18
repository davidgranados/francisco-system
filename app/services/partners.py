from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import DomainError
from app.models import Partner


class PartnerView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    share: Decimal
    telegram_user_id: int | None
    active: bool


class PartnerEntry(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    share: Decimal = Field(gt=0, le=1, decimal_places=4)
    telegram_user_id: int | None = None


async def active_partners(session: AsyncSession) -> list[Partner]:
    rows = await session.scalars(select(Partner).where(Partner.active).order_by(Partner.id))
    return list(rows)


async def list_partners(session: AsyncSession) -> list[PartnerView]:
    return [PartnerView.model_validate(partner) for partner in await active_partners(session)]


async def find_by_name(session: AsyncSession, name: str) -> Partner:
    partner = await session.scalar(
        select(Partner).where(Partner.active, func.lower(Partner.name) == name.strip().lower())
    )
    if partner is None:
        known = ", ".join(p.name for p in await active_partners(session)) or "ninguno"
        raise DomainError(f"No conozco al socio «{name}». Socios registrados: {known}.")
    return partner


async def by_telegram_id(session: AsyncSession, telegram_user_id: int) -> Partner | None:
    return await session.scalar(
        select(Partner).where(Partner.active, Partner.telegram_user_id == telegram_user_id)
    )


async def replace_partners(session: AsyncSession, entries: list[PartnerEntry]) -> list[PartnerView]:
    """Make `entries` the full set of active partners; anyone left out becomes inactive."""
    if sum(entry.share for entry in entries) != 1:
        raise DomainError("Los porcentajes de los socios deben sumar 1 (100 %).")
    names = {entry.name.lower() for entry in entries}
    if len(names) != len(entries):
        raise DomainError("Hay socios repetidos.")
    existing = {p.name.lower(): p for p in await session.scalars(select(Partner))}
    for partner in existing.values():
        if partner.name.lower() not in names:
            partner.active = False
            partner.telegram_user_id = None
    await session.flush()
    for entry in entries:
        partner = existing.get(entry.name.lower())
        if partner is None:
            partner = Partner(name=entry.name)
            session.add(partner)
        partner.share = entry.share
        partner.telegram_user_id = entry.telegram_user_id
        partner.active = True
    await session.flush()
    return await list_partners(session)
