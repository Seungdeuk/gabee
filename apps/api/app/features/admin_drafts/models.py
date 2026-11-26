"""관리자 AI 초안 대기함 `admin_drafts`. 초안 한 건이 한 줄이다.

- notice: 공지 초안(근거 알림에서 만든다). auto 가 참이면 정해 둔 문구로 이미 올린 자동 공지 기록이다.
- reply: 문의 답변 초안(문의 한 건에 하나).
source_key 는 같은 근거로 초안을 두 번 만들지 않게 하는 지문이다(알림 키 묶음의 해시, 또는 문의 번호).
초안에는 회원 이름·연락처·사용자 id 를 담지 않는다. 답변 초안의 문의 번호(ticket_id)만 원래 문의와 잇는다.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

KINDS = ("notice", "reply")
STATUSES = ("pending", "used", "dismissed")  # 대기, 썼음, 버림


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(UTC)


class AdminDraft(Base):
    __tablename__ = "admin_drafts"
    __table_args__ = (
        UniqueConstraint("kind", "source_key", name="uq_admin_drafts_kind_source"),
        Index("ix_admin_drafts_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    kind: Mapped[str] = mapped_column(String(16))  # notice | reply
    source_key: Mapped[str] = mapped_column(String(120))  # 근거 지문(중복 방지)
    ticket_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # reply 만
    category: Mapped[str | None] = mapped_column(String(16), nullable=True)  # notice 종류
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(300))  # 왜 이 초안을 만들었나(관리자가 판단할 근거)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    auto: Mapped[bool] = mapped_column(Boolean, default=False)  # 자동 공지로 이미 올렸나
    notice_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # 자동 공지의 공지 번호
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
