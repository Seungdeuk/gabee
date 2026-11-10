"""문의·신고: 사용자가 앱에서 보낸 글 한 건이 한 줄이다. 서비스 관리자가 상태를 바꾸고 답변한다.

신고에도 사용자가 직접 쓴 글만 담는다(가족 채팅 내용은 붙이지 않는다) — docs/requirements/support.md."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

KINDS = ("inquiry", "report")  # 문의, 신고
STATUSES = ("new", "working", "done")  # 접수, 처리 중, 완료


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(UTC)


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        Index("ix_support_tickets_user_created", "user_id", "created_at"),
        Index("ix_support_tickets_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))  # 보낸 사람
    group_id: Mapped[str | None] = mapped_column(
        ForeignKey("groups.id"), nullable=True
    )  # 보낼 때의 가족
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="new")
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
