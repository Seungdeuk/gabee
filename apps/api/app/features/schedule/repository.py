from datetime import UTC, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember

from .models import Event, EventTopic


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


def topics_of(db: Session, group_id: str, user_id: str) -> list[EventTopic]:
    return list(
        db.scalars(
            select(EventTopic)
            .where(
                EventTopic.group_id == group_id,
                EventTopic.user_id == user_id,
                EventTopic.deleted_at.is_(None),
            )
            .order_by(EventTopic.created_at, EventTopic.id)
        )
    )


def has_any_topic(db: Session, group_id: str, user_id: str) -> bool:
    """지운 주제까지 포함해 한 번이라도 만든 적이 있는가(기본 주제를 다시 만들지 않기 위해)."""
    return (
        db.scalar(
            select(EventTopic.id)
            .where(EventTopic.group_id == group_id, EventTopic.user_id == user_id)
            .limit(1)
        )
        is not None
    )


def get_topic(db: Session, group_id: str, user_id: str, topic_id: str) -> EventTopic | None:
    return db.scalar(
        select(EventTopic).where(
            EventTopic.id == topic_id,
            EventTopic.group_id == group_id,
            EventTopic.user_id == user_id,
            EventTopic.deleted_at.is_(None),
        )
    )


def delete_topic(db: Session, topic: EventTopic) -> None:
    """주제를 소프트 삭제하고, 그 주제를 붙인 일정의 topic_id 는 비운다."""
    topic.deleted_at = datetime.now(UTC)
    db.execute(update(Event).where(Event.topic_id == topic.id).values(topic_id=None))
    db.commit()
