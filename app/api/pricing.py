from datetime import date

from fastapi import APIRouter

from app.api.deps import Session
from app.services import pricing
from app.services.boxes import BoxView
from app.services.pricing import AdjustPricesInput, PriceList

router = APIRouter(prefix="/pricing", tags=["precios"])


@router.get("")
async def price_list(session: Session, day: date | None = None) -> PriceList:
    return await pricing.price_list(session, day)


@router.post("/adjust")
async def adjust_prices(session: Session, data: AdjustPricesInput) -> BoxView:
    return await pricing.adjust_prices(session, data)
