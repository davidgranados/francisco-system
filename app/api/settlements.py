from fastapi import APIRouter, status

from app.api.deps import Session
from app.services import settlements
from app.services.settlements import SettlementInput, SettlementPreview, SettlementView

router = APIRouter(prefix="/settlements", tags=["cierres"])


@router.get("")
async def list_settlements(session: Session, limit: int = 10) -> list[SettlementView]:
    return await settlements.list_settlements(session, limit)


@router.post("/preview")
async def preview_settlement(session: Session, data: SettlementInput) -> SettlementPreview:
    return await settlements.preview_settlement(session, data)


@router.post("", status_code=status.HTTP_201_CREATED)
async def execute_settlement(session: Session, data: SettlementInput) -> SettlementView:
    return await settlements.execute_settlement(session, data)
