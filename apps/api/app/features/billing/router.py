from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import service
from .schemas import (
    AllowanceBudget,
    AllowanceOut,
    AllowanceUseCreate,
    ExpenseCreate,
    ExpenseOut,
    ManagerOut,
    ManagerSet,
    MinorsSet,
    PaymentCreate,
    Reminder,
    Settlement,
    SettleRequest,
    SettleTagOut,
    SubscriptionList,
    SubscriptionOut,
    SubscriptionPatch,
    Summary,
)

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/expenses", response_model=list[ExpenseOut])
def list_expenses(
    month: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[ExpenseOut]:
    return service.list_expenses(db, group_id, service.check_month(month or service.this_month()))


@router.post("/expenses", response_model=ExpenseOut, status_code=201)
def create_expense(
    body: ExpenseCreate,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> ExpenseOut:
    return service.create(db, group_id, user.id, body)


@router.delete("/expenses/{expense_id}", status_code=204)
def delete_expense(
    expense_id: str, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> Response:
    """소프트 삭제: 행은 남기고 `deleted_at` 만 채운다."""
    service.delete_expense(db, group_id, expense_id)
    return Response(status_code=204)


@router.get("/summary", response_model=Summary)
def month_summary(
    month: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Summary:
    return service.summary(db, group_id, service.check_month(month or service.this_month()))


@router.get("/settlement", response_model=Settlement)
def get_settlement(
    month: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Settlement:
    return service.settlement(db, group_id, service.check_month(month or service.this_month()))


@router.get("/settlement/tags", response_model=list[SettleTagOut])
def settle_tags(
    group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> list[SettleTagOut]:
    """정산 대상 고정 태그와 태그별 기본 나눌 사람."""
    return service.settle_tags(db, group_id)


@router.post("/settlement/tag", response_model=Settlement)
def settle(
    body: SettleRequest,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Settlement:
    """'정산하기': 고른 지출에 대상 태그와 나눌 사람을 정하고 바뀐 정산 결과를 돌려준다."""
    return service.settle(db, group_id, user.id, body)


@router.get("/settlement/manager", response_model=ManagerOut)
def get_manager(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> ManagerOut:
    """정산 담당자(월말 알림을 받는 사람). 지정하지 않았으면 그룹을 만든 사람."""
    return service.get_manager(db, group_id, user)


@router.put("/settlement/manager", response_model=ManagerOut)
def set_manager(
    body: ManagerSet,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> ManagerOut:
    return service.set_manager(db, group_id, user, body.user_id)


@router.put("/settlement/minors", response_model=ManagerOut)
def set_minors(
    body: MinorsSet,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> ManagerOut:
    """미성년 자녀 표시(정산 담당자·그룹을 만든 사람만). 있으면 '자녀 대상' 정산은 부모님이 부담한다."""
    return service.set_minors(db, group_id, user, body.user_ids)


@router.get("/settlement/reminder", response_model=Reminder)
def settlement_reminder(
    on: str | None = None,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Reminder:
    """월말 정산 알림. 정산 담당자에게만 show=true 가 내려간다. `on` 은 화면 테스트용 날짜(YYYY-MM-DD)."""
    return service.reminder(db, group_id, user, on)


@router.post("/settlement/payments", response_model=Settlement, status_code=201)
def mark_paid(
    body: PaymentCreate, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> Settlement:
    """송금 목록에 있는 송금 하나를 '송금 완료'로 표시한다."""
    return service.mark_paid(db, group_id, body)


@router.delete("/settlement/payments/{payment_id}", response_model=Settlement)
def undo_paid(
    payment_id: str, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> Settlement:
    return service.undo_paid(db, group_id, payment_id)


@router.get("/subscriptions", response_model=SubscriptionList)
def list_subscriptions(
    group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> SubscriptionList:
    return service.list_subscriptions(db, group_id)


@router.patch("/subscriptions/{item_id}", response_model=SubscriptionOut)
def set_subscription_status(
    item_id: str,
    body: SubscriptionPatch,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    return service.set_subscription_status(db, group_id, item_id, body.status)


@router.get("/allowances", response_model=list[AllowanceOut])
def list_allowances(
    month: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[AllowanceOut]:
    return service.list_allowances(db, group_id, service.check_month(month or service.this_month()))


@router.put("/allowances/{child_id}", response_model=AllowanceOut)
def set_budget(
    child_id: str,
    body: AllowanceBudget,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AllowanceOut:
    month = service.check_month(body.month or service.this_month())
    return service.set_budget(db, group_id, child_id, month, body.budget)


@router.post("/allowances/{child_id}/uses", response_model=AllowanceOut, status_code=201)
def add_use(
    child_id: str,
    body: AllowanceUseCreate,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AllowanceOut:
    return service.add_use(db, group_id, child_id, body)
