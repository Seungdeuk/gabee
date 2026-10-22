from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class Expense(Base):
    """가족 공동 지출. 삭제는 `deleted_at` 을 채우는 소프트 삭제다.
    TODO: 영수증 사진 연결, 균등이 아닌 분담 방식, 월 정산 승인 흐름(원본 billing 참고)."""

    __tablename__ = "expenses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(120))
    amount: Mapped[int] = mapped_column(Integer)  # 원
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    category: Mapped[str] = mapped_column(String(16), default="기타")
    paid_by: Mapped[str] = mapped_column(String(32))  # 결제한 사용자 id
    split_among: Mapped[list[str]] = mapped_column(JSON, default=list)  # 나눌 사용자 id 들
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SettlementPayment(Base):
    """'송금 완료'로 표시한 송금. 송금 목록은 매번 계산하고, 완료된 금액만 여기에 남긴다."""

    __tablename__ = "settlement_payments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    from_user_id: Mapped[str] = mapped_column(String(32))
    to_user_id: Mapped[str] = mapped_column(String(32))
    amount: Mapped[int] = mapped_column(Integer)  # 원
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SubscriptionItem(Base):
    """OTT·통신비 항목의 가족 할인 상태. 금액은 다루지 않는다."""

    __tablename__ = "subscription_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # ott | telecom
    name: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(12), default="check")  # check | available | active
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Allowance(Base):
    """자녀별 월 용돈 예산."""

    __tablename__ = "allowances"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    child_id: Mapped[str] = mapped_column(String(32), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    budget: Mapped[int] = mapped_column(Integer)  # 원


class AllowanceUse(Base):
    __tablename__ = "allowance_uses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    allowance_id: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[int] = mapped_column(Integer)  # 원
    memo: Mapped[str] = mapped_column(String(120), default="")
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
