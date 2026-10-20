from fastapi import APIRouter

from app.api.deps import Paging, Session
from app.services import boxes
from app.services.boxes import BoxProfit, BoxSheet, BoxView
from app.services.pages import Page

router = APIRouter(prefix="/boxes", tags=["cajas"])


@router.get("")
async def list_boxes(
    session: Session, paging: Paging, include_settled: bool = False
) -> Page[BoxView]:
    return await boxes.boxes_page(session, paging, include_settled)


@router.get("/{number}/sheet")
async def box_sheet(session: Session, number: int) -> BoxSheet:
    return await boxes.box_sheet(session, number)


@router.get("/{number}/profit")
async def box_profit(session: Session, number: int) -> BoxProfit:
    return await boxes.box_profit(session, number)
