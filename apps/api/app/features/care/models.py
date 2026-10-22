from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

KINDS = ("condition", "meal", "medication", "walk")  # 컨디션, 식사, 약 복용, 걷기


class CareRecord(Base):
    """돌봄 대상(부모님)의 하루 기록. 같은 날·같은 종류는 하나만 두고 덮어쓴다.
    TODO: 병원 일정, 처방전·사진 연결, 가족 요청, AI 제안·승인(원본 checkin 참고)."""

    __tablename__ = "care_records"
    __table_args__ = (
        UniqueConstraint("group_id", "subject", "kind", "date", name="uq_care_day_kind"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    subject: Mapped[str] = mapped_column(String(40))  # 돌봄 대상 이름(예: 어머니)
    kind: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(String(40))  # 예: 좋아요/보통이에요/힘들어요, 먹었어요, 20분
    note: Mapped[str] = mapped_column(Text, default="")
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    created_by: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


MODES = ("yesno", "number", "condition")  # 예/아니오, 수치(목표 있음), 컨디션
CONDITIONS = ("good", "normal", "bad")  # 좋음, 보통, 나쁨
MEAL_TYPES = ("breakfast", "lunch", "dinner")


class CareItem(Base):
    """데일리 체크 항목. 삭제는 `deleted_at` 을 채우는 소프트 삭제다(기록은 남긴다)."""

    __tablename__ = "care_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(10))
    unit: Mapped[str] = mapped_column(String(8), default="")  # 수치 항목의 단위(ml, 분)
    target: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 수치 항목의 목표
    scheduled_time: Mapped[str] = mapped_column(String(5))  # HH:MM
    meal_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    rule_key: Mapped[str | None] = mapped_column(String(12), nullable=True)  # 추천 규칙이 보는 항목
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CareEntry(Base):
    """항목의 하루 기록. 같은 항목·같은 날은 하나만 두고 덮어쓴다."""

    __tablename__ = "care_entries"
    __table_args__ = (UniqueConstraint("item_id", "date", name="uq_care_entry_day"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    item_id: Mapped[str] = mapped_column(String(32), index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    done: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # 예/아니오 항목
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 수치 항목
    condition: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 컨디션 항목
    recorded_by: Mapped[str] = mapped_column(String(32))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
