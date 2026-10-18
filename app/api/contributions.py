from fastapi import APIRouter, status

from app.api.deps import Session
from app.services import contributions
from app.services.contributions import ContributionInput, ContributionView

router = APIRouter(prefix="/contributions", tags=["aportes"])


@router.get("")
async def list_contributions(session: Session) -> list[ContributionView]:
    return await contributions.list_contributions(session)


@router.post("", status_code=status.HTTP_201_CREATED)
async def record_contribution(session: Session, data: ContributionInput) -> ContributionView:
    return await contributions.record_contribution(session, data)
