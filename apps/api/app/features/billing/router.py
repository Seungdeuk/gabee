from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import repository, service
from .models import Expense
from .schemas import ExpenseCreate, ExpenseOut, Summary

router = APIRouter(prefix="/billing", tags=["billing"])


def _this_month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


@router.get("/expenses", response_model=list[ExpenseOut])
def list_expenses(
    month: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[Expense]:
    return repository.list_month(db, group_id, service.check_month(month or _this_month()))


@router.post("/expenses", response_model=ExpenseOut, status_code=201)
def create_expense(
    body: ExpenseCreate,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Expense:
    return service.create(db, group_id, user.id, body)


@router.get("/summary", response_model=Summary)
def month_summary(
    month: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Summary:
    return service.summary(db, group_id, service.check_month(month or _this_month()))
