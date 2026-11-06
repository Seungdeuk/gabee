"""서비스 공지사항: 서비스 관리자가 쓰고 앱 사용자 모두가 읽는다. 가족 데이터가 아니다(group_id 없음).

읽음 표시는 서버에 남기지 않는다(앱이 폰에 마지막으로 본 공지를 기억한다) — docs/requirements/notices.md."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

CATEGORIES = ("update", "info", "maintenance")  # 업데이트, 안내, 점검


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(UTC)


class Notice(Base):
    __tablename__ = "notices"
    __table_args__ = (Index("ix_notices_created", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    category: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )  # 쓴 서비스 관리자(앱에는 보내지 않는다)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
