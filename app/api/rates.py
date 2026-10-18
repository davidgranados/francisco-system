from datetime import date

from fastapi import APIRouter

from app.api.deps import Session
from app.services import rates
from app.services.rates import RateView, SetRateInput

router = APIRouter(prefix="/rates", tags=["tasa"])


@router.get("/{day}")
async def rate_for(session: Session, day: date) -> RateView:
    return await rates.rate_for(session, day)


@router.put("")
async def set_rate(session: Session, data: SetRateInput) -> RateView:
    return await rates.set_rate(session, data)
