from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.shared.notifications import Notification

from .models import (
    AllowanceEntry,
    AllowancePlan,
    AllowanceRequest,
    BillingSettings,
    Expense,
    SettlementPayment,
    SubscriptionItem,
)


def add(db: Session, expense: Expense) -> Expense:
    db.add(expense)
    db.commit()
    return expense


def get_expense(db: Session, group_id: str, expense_id: str) -> Expense | None:
    return db.scalar(
        select(Expense).where(
            Expense.id == expense_id, Expense.group_id == group_id, Expense.deleted_at.is_(None)
        )
    )


def list_month(db: Session, group_id: str, month: str) -> list[Expense]:
    return list(
        db.scalars(
            select(Expense)
            .where(
                Expense.group_id == group_id,
                Expense.date.like(f"{month}-%"),
                Expense.deleted_at.is_(None),
            )
            .order_by(Expense.date.desc(), Expense.created_at.desc())
        )
    )


def save(db: Session, obj):
    db.add(obj)
    db.commit()
    return obj


def list_payments(db: Session, group_id: str, month: str) -> list[SettlementPayment]:
    return list(
        db.scalars(
            select(SettlementPayment)
            .where(SettlementPayment.group_id == group_id, SettlementPayment.month == month)
            .order_by(SettlementPayment.created_at)
        )
    )


def get_payment(db: Session, group_id: str, payment_id: str) -> SettlementPayment | None:
    return db.scalar(
        select(SettlementPayment).where(
            SettlementPayment.id == payment_id, SettlementPayment.group_id == group_id
        )
    )


def delete(db: Session, obj) -> None:
    db.delete(obj)
    db.commit()


def list_subscriptions(db: Session, group_id: str) -> list[SubscriptionItem]:
    return list(
        db.scalars(
            select(SubscriptionItem)
            .where(SubscriptionItem.group_id == group_id, SubscriptionItem.deleted_at.is_(None))
            .order_by(SubscriptionItem.sort_order)
        )
    )


def max_subscription_order(db: Session, group_id: str) -> int:
    return db.scalar(
        select(func.coalesce(func.max(SubscriptionItem.sort_order), -1)).where(
            SubscriptionItem.group_id == group_id
        )
    )


def subscription_ids_with_expense(db: Session, group_id: str, month: str) -> set[str]:
    """그 달에 이미 지출을 만든 구독 항목 id 들(삭제한 지출은 세지 않는다)."""
    rows = db.scalars(
        select(Expense.subscription_id).where(
            Expense.group_id == group_id,
            Expense.subscription_id.is_not(None),
            Expense.date.like(f"{month}-%"),
            Expense.deleted_at.is_(None),
        )
    )
    return set(rows)


def get_subscription(db: Session, group_id: str, item_id: str) -> SubscriptionItem | None:
    return db.scalar(
        select(SubscriptionItem).where(
            SubscriptionItem.id == item_id,
            SubscriptionItem.group_id == group_id,
            SubscriptionItem.deleted_at.is_(None),
        )
    )


def get_plan(db: Session, group_id: str, child_id: str) -> AllowancePlan | None:
    return db.scalar(
        select(AllowancePlan).where(
            AllowancePlan.group_id == group_id, AllowancePlan.child_id == child_id
        )
    )


def list_entries(db: Session, group_id: str, child_id: str) -> list[AllowanceEntry]:
    """오래된 순(잔액을 차례로 계산하기 위해)."""
    return list(
        db.scalars(
            select(AllowanceEntry)
            .where(AllowanceEntry.group_id == group_id, AllowanceEntry.child_id == child_id)
            .order_by(AllowanceEntry.date, AllowanceEntry.created_at, AllowanceEntry.id)
        )
    )


def get_entry(db: Session, group_id: str, child_id: str, entry_id: str) -> AllowanceEntry | None:
    return db.scalar(
        select(AllowanceEntry).where(
            AllowanceEntry.id == entry_id,
            AllowanceEntry.group_id == group_id,
            AllowanceEntry.child_id == child_id,
        )
    )


def posted_due_dates(db: Session, child_id: str) -> set[str]:
    """주기 지급으로 이미 기록한 지급일(취소한 줄도 센다: 같은 지급일을 다시 만들지 않는다)."""
    return set(
        db.scalars(
            select(AllowanceEntry.plan_due_date).where(
                AllowanceEntry.child_id == child_id, AllowanceEntry.plan_due_date.is_not(None)
            )
        )
    )


def save_all(db: Session, objs: list) -> None:
    db.add_all(objs)
    db.commit()


def get_settings(db: Session, group_id: str) -> BillingSettings | None:
    return db.scalar(select(BillingSettings).where(BillingSettings.group_id == group_id))


MAX_PENDING_REQUESTS = 5  # 자녀 한 명이 동시에 올려 둘 수 있는 대기 요청


def list_requests(db: Session, group_id: str, child_id: str) -> list[AllowanceRequest]:
    """최신순."""
    return list(
        db.scalars(
            select(AllowanceRequest)
            .where(AllowanceRequest.group_id == group_id, AllowanceRequest.child_id == child_id)
            .order_by(AllowanceRequest.created_at.desc(), AllowanceRequest.id.desc())
        )
    )


def get_request(
    db: Session, group_id: str, child_id: str, request_id: str
) -> AllowanceRequest | None:
    return db.scalar(
        select(AllowanceRequest).where(
            AllowanceRequest.id == request_id,
            AllowanceRequest.group_id == group_id,
            AllowanceRequest.child_id == child_id,
        )
    )


def settlement_notice_rows(
    db: Session, group_id: str, user_id: str
) -> list[tuple[str, str | None, object]]:
    """이 사용자가 받은 정산 알림(보낼 돈 알림·재알림)의 (사건, 월, 만든 시각). 재알림을 이미 보냈는지도 여기서 본다."""
    rows = db.execute(
        select(Notification.event, Notification.target_id, Notification.created_at).where(
            Notification.group_id == group_id,
            Notification.user_id == user_id,
            Notification.kind == "billing",
            Notification.event.in_(("settlement_pay", "settlement_remind")),
        )
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]
