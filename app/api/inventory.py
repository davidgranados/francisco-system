from datetime import date

from fastapi import APIRouter, status

from app.api.deps import Session
from app.services import inventory
from app.services.inventory import (
    CountInput,
    CountView,
    LossInput,
    LossView,
    StockRow,
    StockView,
)

router = APIRouter(prefix="/inventory", tags=["inventario"])


@router.get("/stock")
async def stock(session: Session) -> StockView:
    return await inventory.stock(session)


@router.get("/ledger")
async def stock_ledger(session: Session, date_from: date, date_to: date) -> list[StockRow]:
    return await inventory.stock_ledger(session, date_from, date_to)


@router.post("/losses", status_code=status.HTTP_201_CREATED)
async def record_loss(session: Session, data: LossInput) -> LossView:
    return await inventory.record_loss(session, data)


@router.post("/counts", status_code=status.HTTP_201_CREATED)
async def record_count(session: Session, data: CountInput) -> CountView:
    return await inventory.record_count(session, data)
