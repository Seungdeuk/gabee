"""알림 조회·읽음 처리 쿼리. 항상 받는 사람 본인의 것만, 지금도 구성원인 그룹의 것만 다룬다."""

from datetime import datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember
from app.shared.notifications import Notification


def _visible(user_id: str):
    """내 알림 중 지금도 구성원인 그룹의 것(탈퇴한 그룹의 옛 알림은 제외)."""
    return (
        select(Notification)
        .join(
            GroupMember,
            and_(
                GroupMember.group_id == Notification.group_id,
                GroupMember.user_id == Notification.user_id,
            ),
        )
        .where(Notification.user_id == user_id)
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
