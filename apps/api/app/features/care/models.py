from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
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
    # 건너뛰기: 일부러 기록하지 않기로 한 항목. 누락으로 세지 않고 완료도 아니다.
    skipped: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    recorded_by: Mapped[str] = mapped_column(String(32))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class CareMealLog(Base):
    """식단 기록: 그날 아침·점심·저녁에 무엇을 드셨는지. 같은 날·같은 끼니는 하나만 두고 덮어쓴다.
    기록하면 그 끼니의 데일리 체크 항목도 완료로 맞춘다(서비스)."""

    __tablename__ = "care_meal_logs"
    __table_args__ = (UniqueConstraint("group_id", "date", "meal", name="uq_care_meal_log"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    meal: Mapped[str] = mapped_column(String(10))  # breakfast | lunch | dinner
    menu: Mapped[str] = mapped_column(String(60))
    note: Mapped[str] = mapped_column(String(120), default="")
    source: Mapped[str] = mapped_column(String(12), default="typed")  # typed | recommended
    recorded_by: Mapped[str] = mapped_column(String(32))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class CareLocation(Base):
    """동의한 사람이 보낸 위치. 좌표는 로그에 남기지 않고, LOCATION_RETENTION_DAYS 가 지나면 지운다."""

    __tablename__ = "care_locations"
    __table_args__ = (Index("ix_care_locations_user_recorded", "user_id", "recorded_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 기기에서 잰 시각
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
