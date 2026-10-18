from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import today
from app.models import Contribution
from app.services import partners


class ContributionInput(BaseModel):
    partner: str = Field(description="Nombre del socio que pone el dinero")
    amount_usd: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    day: date | None = None
    note: str | None = None


class ContributionView(BaseModel):
    id: int
    partner: str
    day: date
    amount_usd: Decimal
    note: str | None


def _view(contribution: Contribution) -> ContributionView:
    return ContributionView(
        id=contribution.id,
        partner=contribution.partner.name,
        day=contribution.day,
        amount_usd=contribution.amount_usd,
        note=contribution.note,
    )


async def record_contribution(session: AsyncSession, data: ContributionInput) -> ContributionView:
    contribution = Contribution(
        partner=await partners.find_by_name(session, data.partner),
        day=data.day or today(),
        amount_usd=data.amount_usd,
        note=data.note,
    )
    session.add(contribution)
    await session.flush()
    return _view(contribution)


async def list_contributions(session: AsyncSession) -> list[ContributionView]:
    rows = await session.scalars(select(Contribution).order_by(Contribution.day, Contribution.id))
    return [_view(contribution) for contribution in rows]
