from datetime import date

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import Session
from app.config import today
from app.services import expenses
from app.services.expenses import ExpenseInput, ExpenseView

router = APIRouter(prefix="/expenses", tags=["gastos"])


class ReimburseInput(BaseModel):
    day: date | None = Field(default=None, description="Fecha de la devolución; por defecto hoy")


@router.get("/pending")
async def pending(session: Session) -> list[ExpenseView]:
    return await expenses.pending(session)


@router.post("", status_code=status.HTTP_201_CREATED)
async def record_expense(session: Session, data: ExpenseInput) -> ExpenseView:
    return await expenses.record_expense(session, data)


@router.post("/{expense_id}/reimburse")
async def mark_reimbursed(session: Session, expense_id: int, data: ReimburseInput) -> ExpenseView:
    return (await expenses.reimburse(session, [expense_id], data.day or today()))[0]
