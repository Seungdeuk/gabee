from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
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
