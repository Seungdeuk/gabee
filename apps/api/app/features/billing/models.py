from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class Expense(Base):
    """가족 공동 지출. TODO: 영수증 사진 연결, 균등이 아닌 분담 방식, 구독, 월 정산 승인 흐름(원본 billing 참고)."""

    __tablename__ = "expenses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(120))
    amount: Mapped[int] = mapped_column(Integer)  # 원
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    category: Mapped[str] = mapped_column(String(16), default="기타")
    paid_by: Mapped[str] = mapped_column(String(32))  # 결제한 사용자 id
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
