import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.shared.errors import not_found

from . import repository as repo
from .models import Event
from .schemas import EventCreate


def create(db: Session, group_id: str, user_id: str, body: EventCreate) -> Event:
    starts_at = body.starts_at if body.starts_at.tzinfo else body.starts_at.replace(tzinfo=UTC)
    event = Event(
        id=uuid.uuid4().hex[:12],
        group_id=group_id,
        created_by=user_id,
        title=body.title.strip(),
        starts_at=starts_at,
        note=body.note,
        status=body.status,
        source=body.source,
    )
    return repo.add(db, event)


def upcoming(db: Session, group_id: str, include_past: bool = False) -> list[Event]:
    return repo.list_from(db, group_id, None if include_past else datetime.now(UTC))


def confirm(db: Session, group_id: str, event_id: str) -> Event:
    event = repo.get(db, group_id, event_id)
    if event is None:
        raise not_found("일정")
    event.status = "confirmed"
    db.commit()
    return event


def remove(db: Session, group_id: str, event_id: str) -> None:
    event = repo.get(db, group_id, event_id)
    if event is None:
        raise not_found("일정")
    repo.delete(db, event)
