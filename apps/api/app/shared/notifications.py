"""알림함: 일어난 사건을 받는 사람마다 한 줄씩 남기는 기록(앱 안 알림함).

각 기능이 사건이 생긴 자리에서 `notify()` 를 부르고, 조회·읽음 처리는 features/notifications 가 맡는다.
다른 기능이 서로의 내부를 import 하지 않도록 모델과 기록 함수는 shared 에 둔다."""

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.features.family_group.models import GroupMember
from app.shared.db import Base
from app.shared.push import queue_push

logger = logging.getLogger(__name__)

# 알림 분류. 소통(가족 채팅) 메시지 알림은 알림함에 담지 않는다.
# support(고객센터 답변)는 사용자 개인에게 가는 알림이라 group_id 가 없다.
KINDS = ("schedule", "billing", "care", "family_group", "ai_record", "support")


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
    group_id: Mapped[str | None] = mapped_column(
        ForeignKey("groups.id"), nullable=True
    )  # 가족과 무관한 알림은 비움
    kind: Mapped[str] = mapped_column(String(16))
    event: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def notify(
    db: Session,
    *,
    group_id: str | None,
    kind: str,
    event: str,
    recipients: Iterable[str],
    title: str,
    body: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    actor_user_id: str | None = None,
) -> int:
    """받는 사람마다 알림 한 줄을 남기고 만든 개수를 돌려준다. 커밋은 부르는 쪽이 한다.

    그룹 구성원이 아닌 사람과 행동한 본인(`actor_user_id`)은 건너뛰고, 같은 사람은 한 번만 받는다.
    `group_id=None` 은 가족과 무관한 개인 알림(고객센터 답변 등)이라 구성원 확인 없이 받는 사람에게 그대로 남긴다.
    저장이 실패해도 예외를 밖으로 내지 않는다(원래 기능이 알림 때문에 실패하면 안 된다).
    문구에는 금액·위치·건강 정보·AI 요약·채팅 내용을 넣지 않는다 — 고정 템플릿만 쓴다."""
    if kind not in KINDS:
        raise ValueError(f"알 수 없는 알림 분류: {kind}")  # 개발 실수는 일찍 드러낸다
    targets = [uid for uid in dict.fromkeys(recipients) if uid != actor_user_id]
    # begin_nested() 는 savepoint 를 열기 전에 flush 한다. 호출한 쪽이 쌓아 둔 변경의 오류가 알림 실패로 위장돼
    # 삼켜지지 않도록 try 밖에서 먼저 flush 해서 그 오류는 호출한 쪽에게 돌려준다.
    db.flush()
    try:
        with db.begin_nested():  # 실패해도 앞선 변경은 그대로 둔다
            created = 0
            new_rows: list[Notification] = []
            for uid in targets:
                if group_id is not None and db.get(GroupMember, (group_id, uid)) is None:
                    continue
                row = Notification(
                    id=_uid(),
                    user_id=uid,
                    group_id=group_id,
                    kind=kind,
                    event=event,
                    title=title,
                    body=body,
                    target_type=target_type,
                    target_id=target_id,
                    actor_user_id=actor_user_id,
                )
                db.add(row)
                new_rows.append(row)
                created += 1
        _queue_pushes(db, new_rows)
        return created
    except Exception as exc:
        # 개인 정보는 남기지 않는다(분류·사건·예외 종류만)
        logger.warning("notify failed kind=%s event=%s error=%s", kind, event, type(exc).__name__)
        return 0


def _queue_pushes(db: Session, rows: list[Notification]) -> None:
    """방금 저장한 알림마다 푸시를 예약한다(커밋 뒤에 발송). 푸시 쪽 오류는 알림 저장에 영향을 주지 않는다."""
    for row in rows:
        try:
            queue_push(
                db,
                user_ids=[row.user_id],
                kind=row.kind,
                title=row.title,
                body=None,  # 알림함 사건은 고정 제목만 푸시한다
                data={
                    "notification_id": row.id,
                    "kind": row.kind,
                    "event": row.event,
                    "target_type": row.target_type,
                    "target_id": row.target_id,
                },
            )
        except Exception as exc:
            logger.warning("push queue failed kind=%s error=%s", row.kind, type(exc).__name__)
