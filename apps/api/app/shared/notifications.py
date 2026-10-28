"""알림함: 일어난 사건을 받는 사람마다 한 줄씩 남기는 기록(앱 안 알림함).

각 기능이 사건이 생긴 자리에서 `notify()` 를 부르고, 조회·읽음 처리는 features/notifications 가 맡는다.
다른 기능이 서로의 내부를 import 하지 않도록 모델과 기록 함수는 shared 에 둔다."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

# 알림 분류. 소통(가족 채팅) 메시지 알림은 알림함에 담지 않는다.
KINDS = ("schedule", "billing", "care", "family_group", "ai_record")


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(UTC)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_user_read", "user_id", "read_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))  # 받는 사람
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"))
    kind: Mapped[str] = mapped_column(String(16))
    event: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
