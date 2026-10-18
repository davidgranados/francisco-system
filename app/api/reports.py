from datetime import date

from fastapi import APIRouter

from app.api.deps import Session
from app.services import reports
from app.services.reports import CashFlow, PeriodInput, PeriodSummary

router = APIRouter(prefix="/reports", tags=["reportes"])


@router.get("/summary")
async def summary(session: Session, date_from: date, date_to: date) -> PeriodSummary:
    return await reports.summary(session, PeriodInput(date_from=date_from, date_to=date_to))


@router.get("/cash")
async def cash_flow(
    session: Session, date_from: date | None = None, date_to: date | None = None
) -> CashFlow:
    return await reports.cash_flow(session, date_from, date_to)
