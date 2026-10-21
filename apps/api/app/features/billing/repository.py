from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Expense


def add(db: Session, expense: Expense) -> Expense:
    db.add(expense)
    db.commit()
    return expense


def list_month(db: Session, group_id: str, month: str) -> list[Expense]:
    return list(
        db.scalars(
            select(Expense)
            .where(Expense.group_id == group_id, Expense.date.like(f"{month}-%"))
            .order_by(Expense.date.desc(), Expense.created_at.desc())
        )
    )
