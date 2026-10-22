from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Allowance,
    AllowanceUse,
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
            .where(SubscriptionItem.group_id == group_id)
            .order_by(SubscriptionItem.sort_order)
        )
    )


def add_subscriptions(db: Session, items: list[SubscriptionItem]) -> None:
    db.add_all(items)
    db.commit()


def get_subscription(db: Session, group_id: str, item_id: str) -> SubscriptionItem | None:
    return db.scalar(
        select(SubscriptionItem).where(
            SubscriptionItem.id == item_id, SubscriptionItem.group_id == group_id
        )
    )


def get_allowance(db: Session, group_id: str, child_id: str, month: str) -> Allowance | None:
    return db.scalar(
        select(Allowance).where(
            Allowance.group_id == group_id,
            Allowance.child_id == child_id,
            Allowance.month == month,
        )
    )


def allowance_used(db: Session, allowance_id: str) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(AllowanceUse.amount), 0)).where(
            AllowanceUse.allowance_id == allowance_id
        )
    )


def list_uses(db: Session, allowance_id: str) -> list[AllowanceUse]:
    return list(
        db.scalars(
            select(AllowanceUse)
            .where(AllowanceUse.allowance_id == allowance_id)
            .order_by(AllowanceUse.date.desc(), AllowanceUse.created_at.desc())
        )
    )


def save_all(db: Session, objs: list) -> None:
    db.add_all(objs)
    db.commit()


def get_settings(db: Session, group_id: str) -> BillingSettings | None:
    return db.scalar(select(BillingSettings).where(BillingSettings.group_id == group_id))
