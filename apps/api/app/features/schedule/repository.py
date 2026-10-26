from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember

from .models import Event


def _visible(user_id: str | None) -> list:
    """삭제되지 않은 일정. user_id 를 주면 그 사람의 줄과, 주인이 없던 옛 줄(그룹 전체가 봄)만 남긴다."""
    conditions = [Event.deleted_at.is_(None)]
    if user_id is not None:
        conditions.append(or_(Event.user_id == user_id, Event.user_id.is_(None)))
    return conditions


def add_all(db: Session, events: list[Event]) -> None:
    # 원본이 먼저 들어가도록 순서를 지킨다(복사본의 origin_id 가 원본을 가리킨다)
    db.add_all(events)
    db.commit()


def get(db: Session, group_id: str, event_id: str, user_id: str | None = None) -> Event | None:
    return db.scalar(
        select(Event).where(Event.id == event_id, Event.group_id == group_id, *_visible(user_id))
    )


def list_from(
    db: Session, group_id: str, since: datetime | None, user_id: str | None = None
) -> list[Event]:
    q = (
        select(Event)
        .where(Event.group_id == group_id, *_visible(user_id))
        .order_by(Event.starts_at)
    )
    if since is not None:
        q = q.where(Event.starts_at >= since)
    return list(db.scalars(q))


def member_ids(db: Session, group_id: str, user_ids: list[str]) -> set[str]:
    rows = db.scalars(
        select(GroupMember.user_id).where(
            GroupMember.group_id == group_id, GroupMember.user_id.in_(user_ids)
        )
    )
    return set(rows)


def soft_delete(db: Session, event: Event) -> None:
    event.deleted_at = datetime.now(UTC)
    db.commit()
