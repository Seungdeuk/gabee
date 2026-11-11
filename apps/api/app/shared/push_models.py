"""푸시 알림용 테이블: 기기 푸시 토큰과 사용자별 푸시 설정.

가족(그룹)과 무관한 개인 데이터라 group_id 가 없다. 발송 규칙은 app/shared/push.py,
조회·저장 API 는 features/notifications 가 맡는다."""

import uuid
from datetime import UTC, datetime, time

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(UTC)


class PushToken(Base):
    """기기 하나의 Expo 푸시 토큰. 한 사용자가 기기를 여러 개 가진다. 같은 기기에 다른 사람이 로그인하면 소유자가 옮겨 간다."""

    __tablename__ = "push_tokens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True)
    platform: Mapped[str] = mapped_column(String(16))  # android / ios
    device_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ScheduledPushLog(Base):
    """예약 푸시를 이미 보냈다는 기록(고유 키). 같은 일정·같은 시작 시각·같은 날의 푸시가 두 번 가지 않게 먼저 선점한 쪽만 보낸다.
    키는 `event:<일정 id>:<시작 시각>` 또는 `todo:<할 일 id>:<날짜>` 처럼 일정을 고치면 달라지는 값이다. 내용·제목은 담지 않는다."""

    __tablename__ = "scheduled_push_log"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PushSetting(Base):
    """사용자별 푸시 설정. 줄이 없으면 기본값(켬, full, 끈 분류 없음, 방해금지 없음)으로 본다."""

    __tablename__ = "push_settings"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    preview_mode: Mapped[str] = mapped_column(String(16), default="full")  # full / sender / hidden
    muted_kinds: Mapped[list[str]] = mapped_column(JSON, default=list)
    quiet_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
