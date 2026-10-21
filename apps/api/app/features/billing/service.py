import re
import uuid

from sqlalchemy.orm import Session

from app.features.family_group import repository as group_repo
from app.shared.errors import bad_request

from . import repository as repo
from .models import Expense
from .schemas import Balance, ExpenseCreate, Summary

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def check_month(month: str) -> str:
    if not _MONTH.match(month):
        raise bad_request("invalid_month", "월은 YYYY-MM 형식이어야 해요")
    return month


def create(db: Session, group_id: str, user_id: str, body: ExpenseCreate) -> Expense:
    return repo.add(
        db,
        Expense(
            id=uuid.uuid4().hex[:12],
            group_id=group_id,
            paid_by=user_id,
            title=body.title.strip(),
            amount=body.amount,
            date=body.date.isoformat(),
            category=body.category,
        ),
    )


def summary(db: Session, group_id: str, month: str) -> Summary:
    """그 달 지출을 구성원 수로 똑같이 나눴을 때 사람별로 받을 돈/낼 돈. 나누어떨어지지 않는 1원 단위는 버린다."""
    expenses = repo.list_month(db, group_id, month)
    members = group_repo.members(db, group_id)
    total = sum(e.amount for e in expenses)
    share = total // len(members) if members else 0
    paid: dict[str, int] = {}
    for e in expenses:
        paid[e.paid_by] = paid.get(e.paid_by, 0) + e.amount
    balances = [
        Balance(
            user_id=m.id,
            name=m.name,
            paid=paid.get(m.id, 0),
            share=share,
            balance=paid.get(m.id, 0) - share,
        )
        for m in members
    ]
    return Summary(month=month, total=total, count=len(expenses), balances=balances)
