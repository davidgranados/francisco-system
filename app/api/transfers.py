from fastapi import APIRouter

from app.api.deps import Paging, Session
from app.services import transfers
from app.services.pages import Page
from app.services.transfers import TransferView

router = APIRouter(prefix="/transfers", tags=["movimientos de dinero"])


@router.get("")
async def list_transfers(session: Session, paging: Paging) -> Page[TransferView]:
    return await transfers.transfers_page(session, paging)
