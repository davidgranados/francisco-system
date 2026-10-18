from datetime import date

from fastapi import APIRouter, status

from app.api.deps import Session
from app.services import sales
from app.services.purchases import VoidInput
from app.services.sales import RegisteredSale, SaleInput, SaleView

router = APIRouter(prefix="/sales", tags=["ventas"])


@router.get("")
async def list_sales(session: Session, day: date | None = None) -> list[SaleView]:
    return await sales.list_sales(session, day)


@router.post("", status_code=status.HTTP_201_CREATED)
async def record_sale(session: Session, data: SaleInput) -> RegisteredSale:
    return await sales.record_sale(session, data)


@router.post("/{sale_id}/void")
async def void_sale(session: Session, sale_id: int, data: VoidInput) -> SaleView:
    return await sales.void_sale(session, sale_id, data)
