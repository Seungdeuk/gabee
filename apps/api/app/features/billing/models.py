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
    # 정산 대상 태그: parents(부모님 대상) | children(자녀 대상) | all(가족 전체) | custom(직접 고르기)
    target_tag: Mapped[str] = mapped_column(String(10), default="all", server_default="all")
    # 정산하기를 누른 시각과 사람. 비어 있으면 아직 정산하지 않은(미정산) 지출이다.
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 구독 항목에서 만든 지출이면 그 항목 id. 같은 달에 같은 항목으로 두 번 만들지 않는 데 쓴다.
    subscription_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BillingSettings(Base):
    """가족 그룹의 가계 설정. 정산 담당자(월말 알림을 받는 사람). 행이 없으면 그룹을 만든 사람이 담당자다."""

    __tablename__ = "billing_settings"

    group_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    manager_id: Mapped[str] = mapped_column(String(32))
    # 미성년 자녀 id 들. 있으면 '자녀 대상' 정산은 부모님이 부담한다(가족 구성원 모델에 나이 정보가 아직 없어 여기에 둔다).
    minor_ids: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


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
    """OTT·통신비 항목과 가족 할인 상태. 월 청구 금액·결합 할인 금액·결제일은 사용자가 청구서를 보고 직접 입력한
    값만 저장하고, 할인을 계산하거나 보장하지 않는다. 삭제는 `deleted_at` 소프트 삭제다."""

    __tablename__ = "subscription_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # ott | telecom
    name: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(12), default="check")  # check | available | active
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    carrier: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )  # skt | kt | lgu | mvno | other (통신비만)
    monthly_fee: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 월 청구 금액(원): 청구서에 찍힌, 할인이 이미 빠진 실제 금액
    discount_amount: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 결합 할인 금액(원): 청구서를 보고 직접 입력한 참고 값. 정가 = 월 청구 금액 + 할인 금액
    billing_day: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 매월 결제일 1~31
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # 매달 '구독료 지출 만들기'가 이 항목으로 만드는 지출의 결제한 사람과 나눌 사람.
    # split_among 이 비어 있으면 가족 전체다. payer_id 가 없으면 지출을 만들지 않는다.
    payer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    split_among: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")


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
