from fastapi import APIRouter, status

from app.api.deps import Session
from app.services import expenses
from app.services.expenses import ExpenseInput, ExpenseView, ReimburseInput

router = APIRouter(prefix="/expenses", tags=["gastos"])


@router.get("/pending")
async def pending(session: Session) -> list[ExpenseView]:
    return await expenses.pending(session)


@router.post("", status_code=status.HTTP_201_CREATED)
async def record_expense(session: Session, data: ExpenseInput) -> ExpenseView:
    return await expenses.record_expense(session, data)


@router.post("/{expense_id}/reimburse")
async def mark_reimbursed(session: Session, expense_id: int, data: ReimburseInput) -> ExpenseView:
    return await expenses.mark_reimbursed(session, expense_id, data)
