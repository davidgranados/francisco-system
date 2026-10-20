from fastapi import APIRouter, status

from app.api.deps import Paging, Session
from app.services import settlements
from app.services.pages import Page
from app.services.settlements import SettlementInput, SettlementPreview, SettlementView

router = APIRouter(prefix="/settlements", tags=["cierres"])


@router.get("")
async def list_settlements(session: Session, paging: Paging) -> Page[SettlementView]:
    return await settlements.settlements_page(session, paging)


@router.post("/preview")
async def preview_settlement(session: Session, data: SettlementInput) -> SettlementPreview:
    return await settlements.preview_settlement(session, data)


@router.post("", status_code=status.HTTP_201_CREATED)
async def execute_settlement(session: Session, data: SettlementInput) -> SettlementView:
    return await settlements.execute_settlement(session, data)
