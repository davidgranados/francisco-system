from fastapi import APIRouter, status

from app.api.deps import Session
from app.services import purchases
from app.services.purchases import PurchaseInput, PurchaseView, RegisteredPurchase, VoidInput

router = APIRouter(prefix="/purchases", tags=["compras"])


@router.get("")
async def list_purchases(session: Session, limit: int = 20) -> list[PurchaseView]:
    return await purchases.list_purchases(session, limit)


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_purchase(session: Session, data: PurchaseInput) -> RegisteredPurchase:
    return await purchases.register_purchase(session, data)


@router.post("/{purchase_id}/void")
async def void_purchase(session: Session, purchase_id: int, data: VoidInput) -> PurchaseView:
    return await purchases.void_purchase(session, purchase_id, data)
