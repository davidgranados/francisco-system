from fastapi import APIRouter

from app.api.deps import Session
from app.services import funds
from app.services.funds import FundBalances

router = APIRouter(prefix="/funds", tags=["fondos"])


@router.get("/balances")
async def balances(session: Session) -> FundBalances:
    return await funds.balances(session)
