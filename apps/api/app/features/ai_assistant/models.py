from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class Photo(Base):
    """앱이 올린 사진. status: received(받음) → (TODO) analyzed(분류·OCR 완료) | needs_review | failed.
    TODO: 분류·OCR·문서 저장·RAG 질의·주간 리포트·위치 기록(원본 capture, agent 참고)."""

    __tablename__ = "photos"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    uploaded_by: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(60))
    size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="received")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
