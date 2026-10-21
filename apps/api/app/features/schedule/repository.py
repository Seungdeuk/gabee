from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Event


def add(db: Session, event: Event) -> Event:
    db.add(event)
    db.commit()
    return event


def get(db: Session, group_id: str, event_id: str) -> Event | None:
    event = db.get(Event, event_id)
    return event if event and event.group_id == group_id else None


def list_from(db: Session, group_id: str, since: datetime | None) -> list[Event]:
    q = select(Event).where(Event.group_id == group_id).order_by(Event.starts_at)
    if since is not None:
        q = q.where(Event.starts_at >= since)
    return list(db.scalars(q))


def delete(db: Session, event: Event) -> None:
    db.delete(event)
    db.commit()
