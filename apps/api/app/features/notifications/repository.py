"""알림 조회·읽음 처리 쿼리. 항상 받는 사람 본인의 것만, 지금도 구성원인 그룹의 것과 개인 알림만 다룬다."""

from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember
from app.shared.notifications import KINDS, Notification
from app.shared.push_models import PushSetting, PushToken


def _visible(user_id: str):
    """내 알림 중 지금도 구성원인 그룹의 것(탈퇴한 그룹의 옛 알림은 제외)과 그룹과 무관한 개인 알림.
    없앤 분류(돌봄·기록)의 옛 행은 DB 에 남아 있어도 보이지 않는다."""
    return (
        select(Notification)
        .outerjoin(
            GroupMember,
            and_(
                GroupMember.group_id == Notification.group_id,
                GroupMember.user_id == Notification.user_id,
            ),
        )
        .where(
            Notification.user_id == user_id,
            Notification.kind.in_(KINDS),
            or_(Notification.group_id.is_(None), GroupMember.user_id.is_not(None)),
        )
    )


def list_page(
    db: Session,
    user_id: str,
    kind: str | None,
    limit: int,
    after: tuple[datetime, str] | None,
) -> list[Notification]:
    query = _visible(user_id)
    if kind:
        query = query.where(Notification.kind == kind)
    if after is not None:
        created_at, last_id = after
        query = query.where(
            or_(
                Notification.created_at < created_at,
                and_(Notification.created_at == created_at, Notification.id < last_id),
            )
        )
    query = query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    return list(db.scalars(query))


def unread_by_kind(db: Session, user_id: str) -> dict[str, int]:
    visible = _visible(user_id).where(Notification.read_at.is_(None)).subquery()
    rows = db.execute(select(visible.c.kind, func.count()).group_by(visible.c.kind)).all()
    return {kind: count for kind, count in rows}


def get_visible(db: Session, user_id: str, notification_id: str) -> Notification | None:
    return db.scalars(_visible(user_id).where(Notification.id == notification_id)).first()


def mark_read(db: Session, user_id: str, notification_id: str, now: datetime) -> None:
    """아직 안 읽은 경우에만 읽은 시각을 적는다(이미 읽은 것은 시각을 바꾸지 않는다)."""
    db.execute(
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=now)
    )


def mark_all_read(db: Session, user_id: str, kind: str | None, now: datetime) -> int:
    unread = _visible(user_id).where(Notification.read_at.is_(None))
    if kind:
        unread = unread.where(Notification.kind == kind)
    ids = [row.id for row in db.scalars(unread)]
    if not ids:
        return 0
    db.execute(update(Notification).where(Notification.id.in_(ids)).values(read_at=now))
    return len(ids)


def get_push_setting(db: Session, user_id: str) -> PushSetting | None:
    return db.get(PushSetting, user_id)


def save_push_setting(db: Session, user_id: str, values: dict) -> PushSetting:
    """사용자의 푸시 설정 줄을 만들거나 덮어쓴다(커밋은 부르는 쪽)."""
    row = db.get(PushSetting, user_id)
    if row is None:
        row = PushSetting(user_id=user_id)
        db.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_at = datetime.now(UTC)
    return row


def upsert_push_token(
    db: Session, user_id: str, token: str, platform: str, device_label: str | None
) -> None:
    """토큰을 등록한다. 이미 있으면(다른 사용자가 쓰던 기기 포함) 소유자와 정보를 갱신한다(커밋은 부르는 쪽)."""
    row = db.scalar(select(PushToken).where(PushToken.token == token))
    if row is None:
        db.add(
            PushToken(user_id=user_id, token=token, platform=platform, device_label=device_label)
        )
        return
    row.user_id, row.platform, row.device_label = user_id, platform, device_label
    row.last_seen_at = datetime.now(UTC)


def delete_push_token(db: Session, user_id: str, token: str) -> None:
    """내 토큰만 지운다. 없거나 남의 것이면 아무것도 하지 않는다(커밋은 부르는 쪽)."""
    db.execute(delete(PushToken).where(PushToken.token == token, PushToken.user_id == user_id))
