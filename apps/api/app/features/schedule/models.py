import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

from .constants import KIND_APPOINTMENT, RECIPIENT_WAITING, SUGGESTION_PENDING


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(UTC)


class Event(Base):
    """일정. 사람마다 자기 줄(`user_id`)을 갖고, 공유하면 받는 사람의 복사본이 생긴다(`origin_id` 가 원본).

    새 컬럼은 코드를 옮기는 동안 비어 있을 수 있어 nullable 이거나 기본값이 있다.
    제거 예정: starts_at(→ start_date·start_time), note(→ memo), created_by(→ user_id), status.
    삭제는 `deleted_at` 을 채우는 소프트 삭제다. source: manual | chat | photo | request.
    """

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(120))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="confirmed")
    source: Mapped[str] = mapped_column(String(16), default="manual")
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    kind: Mapped[int] = mapped_column(Integer, default=KIND_APPOINTMENT, server_default="1")
    who_ids: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    place: Mapped[str] = mapped_column(String(200), default="", server_default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    # start_time 이나 end_time 이 비어 있으면 시간 없음, 종일은 00:00~23:59
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    memo: Mapped[str] = mapped_column(Text, default="", server_default="")
    checked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    origin_id: Mapped[str | None] = mapped_column(
        ForeignKey("events.id"), nullable=True, index=True
    )
    suggestion_id: Mapped[str | None] = mapped_column(
        ForeignKey("events_suggestions.id"), nullable=True
    )
    request_id: Mapped[str | None] = mapped_column(
        ForeignKey("events_requests.id"), nullable=True, index=True
    )
    recip_id: Mapped[str | None] = mapped_column(
        ForeignKey("events_request_recipients.id"), nullable=True
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventRequest(Base):
    """부탁 본문. 부탁한 사람은 한 명이라 `user_id` 컬럼으로 둔다. 받는 사람은 `events_request_recipients`."""

    __tablename__ = "events_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)  # 부탁한 사람
    title: Mapped[str] = mapped_column(String(120))
    place: Mapped[str] = mapped_column(String(200), default="", server_default="")
    memo: Mapped[str] = mapped_column(Text, default="", server_default="")
    start_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventRequestRecipient(Base):
    """받는 사람별 답. 부탁한 사람은 본문(`events_requests.user_id`)에서 읽는다."""

    __tablename__ = "events_request_recipients"
    __table_args__ = (UniqueConstraint("request_id", "user_id", name="uq_events_recipients"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)  # 받는 사람
    request_id: Mapped[str] = mapped_column(ForeignKey("events_requests.id"), index=True)
    status: Mapped[int] = mapped_column(
        Integer, default=RECIPIENT_WAITING, server_default=str(RECIPIENT_WAITING)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventSuggestion(Base):
    """미리 저장해 두는 추천. 사람마다 따로. 시간·메모는 없고 사용자가 등록 화면에서 입력한다."""

    __tablename__ = "events_suggestions"
    __table_args__ = (
        Index("ix_events_suggestions_group_user_status", "group_id", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(120))
    place: Mapped[str] = mapped_column(String(200), default="", server_default="")
    kind: Mapped[int] = mapped_column(Integer, default=KIND_APPOINTMENT, server_default="1")
    start_date: Mapped[date] = mapped_column(Date)
    status: Mapped[int] = mapped_column(
        Integer, default=SUGGESTION_PENDING, server_default=str(SUGGESTION_PENDING)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
