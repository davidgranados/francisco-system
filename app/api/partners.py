from fastapi import APIRouter

from app.api.deps import Session
from app.services import partners
from app.services.partners import PartnerView

router = APIRouter(prefix="/partners", tags=["socios"])


@router.get("")
async def list_partners(session: Session) -> list[PartnerView]:
    return await partners.list_partners(session)
