"""알림 조회·읽음 처리 업무 규칙."""

import base64
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.errors import bad_request, not_found

from . import repository as repo
from .schemas import (
    NotificationList,
    NotificationOut,
    PushSettingsIn,
    PushSettingsOut,
    PushTokenDelete,
    PushTokenIn,
    ReadAllResult,
    UnreadCount,
)


def _encode_cursor(row) -> str:
    raw = f"{row.created_at.isoformat()}|{row.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        stamp, last_id = raw.split("|", 1)
        return datetime.fromisoformat(stamp), last_id
    except ValueError as exc:  # 깨진 base64·형식은 400 으로 돌려준다
        raise bad_request("invalid_cursor", "이어 볼 위치가 올바르지 않아요") from exc


def list_notifications(
    db: Session, user: User, kind: str | None, limit: int, cursor: str | None
) -> NotificationList:
    after = _decode_cursor(cursor) if cursor else None
    rows = repo.list_page(db, user.id, kind, limit + 1, after)
    page = rows[:limit]
    next_cursor = _encode_cursor(page[-1]) if len(rows) > limit else None
    return NotificationList(
        items=[NotificationOut.model_validate(r) for r in page], next_cursor=next_cursor
    )


def unread_count(db: Session, user: User) -> UnreadCount:
    by_kind = repo.unread_by_kind(db, user.id)
    return UnreadCount(total=sum(by_kind.values()), by_kind=by_kind)


def read_one(db: Session, user: User, notification_id: str) -> NotificationOut:
    """남의 알림이거나 지금 볼 수 없는 알림이면 있는지도 알려 주지 않고 404."""
    if repo.get_visible(db, user.id, notification_id) is None:
        raise not_found("알림")
    repo.mark_read(db, user.id, notification_id, datetime.now(UTC))
    db.commit()
    return NotificationOut.model_validate(repo.get_visible(db, user.id, notification_id))


def read_all(db: Session, user: User, kind: str | None) -> ReadAllResult:
    updated = repo.mark_all_read(db, user.id, kind, datetime.now(UTC))
    db.commit()
    return ReadAllResult(updated=updated)


def get_push_settings(db: Session, user: User) -> PushSettingsOut:
    """내 푸시 설정. 저장한 적이 없으면 기본값(줄은 만들지 않는다)."""
    row = repo.get_push_setting(db, user.id)
    return PushSettingsOut.model_validate(row, from_attributes=True) if row else PushSettingsOut()


def put_push_settings(db: Session, user: User, body: PushSettingsIn) -> PushSettingsOut:
    row = repo.save_push_setting(db, user.id, body.model_dump())
    db.commit()
    return PushSettingsOut.model_validate(row, from_attributes=True)


def register_push_token(db: Session, user: User, body: PushTokenIn) -> None:
    repo.upsert_push_token(db, user.id, body.token, body.platform, body.device_label)
    db.commit()


def unregister_push_token(db: Session, user: User, body: PushTokenDelete) -> None:
    repo.delete_push_token(db, user.id, body.token)
    db.commit()
