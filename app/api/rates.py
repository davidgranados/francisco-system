from datetime import date

from fastapi import APIRouter

from app.api.deps import Paging, Session
from app.services import rates
from app.services.pages import Page
from app.services.rates import ExchangeRateRow, RateView, SetRateInput

router = APIRouter(prefix="/rates", tags=["tasa"])


@router.get("")
async def list_rates(session: Session, paging: Paging) -> Page[ExchangeRateRow]:
    return await rates.rates_page(session, paging)


@router.get("/{day}")
async def rate_for(session: Session, day: date) -> RateView:
    return await rates.rate_for(session, day)


@router.put("")
async def set_rate(session: Session, data: SetRateInput) -> RateView:
    return await rates.set_rate(session, data)
