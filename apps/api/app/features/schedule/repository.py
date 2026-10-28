from datetime import UTC, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember

from .models import Event, EventRequest, EventRequestRecipient, EventTopic


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


def add_pending(db: Session, events: list[Event]) -> None:
    """commit 없이 세션에만 올린다(부른 쪽이 한 트랜잭션으로 commit 한다)."""
    db.add_all(events)


def get(db: Session, group_id: str, event_id: str, user_id: str | None = None) -> Event | None:
    return db.scalar(
        select(Event).where(Event.id == event_id, Event.group_id == group_id, *_visible(user_id))
    )


def get_including_deleted(db: Session, group_id: str, event_id: str) -> Event | None:
    """지워진 줄까지 포함해 그룹 안의 한 줄을 읽는다(공유 출처를 밝히기 위해)."""
    return db.scalar(select(Event).where(Event.id == event_id, Event.group_id == group_id))


def copies_of(db: Session, group_id: str, root_id: str) -> list[Event]:
    """원본에서 나온 복사본들(지워진 것 포함), 만들어진 순서대로."""
    return list(
        db.scalars(
            select(Event)
            .where(Event.group_id == group_id, Event.origin_id == root_id)
            .order_by(Event.created_at, Event.id)
        )
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


def get_request(db: Session, group_id: str, request_id: str) -> EventRequest | None:
    return db.scalar(
        select(EventRequest).where(EventRequest.id == request_id, EventRequest.group_id == group_id)
    )


def recipients_of(db: Session, request_ids: list[str]) -> list[EventRequestRecipient]:
    """부탁들의 받는 사람 줄, 만든 순서대로."""
    return list(
        db.scalars(
            select(EventRequestRecipient)
            .where(EventRequestRecipient.request_id.in_(request_ids))
            .order_by(EventRequestRecipient.created_at, EventRequestRecipient.id)
        )
    )


def requests_for(db: Session, group_id: str, user_id: str) -> list[EventRequest]:
    """내가 보냈거나 내가 받는 사람인 부탁, 최신순(같으면 id)."""
    received = select(EventRequestRecipient.request_id).where(
        EventRequestRecipient.group_id == group_id, EventRequestRecipient.user_id == user_id
    )
    return list(
        db.scalars(
            select(EventRequest)
            .where(
                EventRequest.group_id == group_id,
                or_(EventRequest.user_id == user_id, EventRequest.id.in_(received)),
            )
            .order_by(EventRequest.created_at.desc(), EventRequest.id)
        )
    )


def my_recipient(db: Session, request_id: str, user_id: str) -> EventRequestRecipient | None:
    return db.scalar(
        select(EventRequestRecipient).where(
            EventRequestRecipient.request_id == request_id,
            EventRequestRecipient.user_id == user_id,
        )
    )


def live_events_of_requests(db: Session, request_ids: list[str], user_id: str) -> list[Event]:
    """내가 수락해서 만든, 지워지지 않은 일정들."""
    return list(
        db.scalars(
            select(Event)
            .where(
                Event.request_id.in_(request_ids),
                Event.user_id == user_id,
                Event.deleted_at.is_(None),
            )
            .order_by(Event.created_at, Event.id)
        )
    )


def live_events_of_recipient(db: Session, recip_id: str) -> list[Event]:
    """이 답 줄로 만들어진, 지워지지 않은 일정들."""
    return list(
        db.scalars(select(Event).where(Event.recip_id == recip_id, Event.deleted_at.is_(None)))
    )
