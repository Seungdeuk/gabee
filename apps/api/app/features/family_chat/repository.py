from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.family_group.models import User

from .models import Message


def add(db: Session, message: Message) -> Message:
    db.add(message)
    db.commit()
    return message


def list_after(db: Session, group_id: str, after_id: int, limit: int) -> list[tuple[Message, str]]:
    """after_id 보다 새로운 메시지를 오래된 순으로. (앱이 몇 초마다 새 메시지만 가져오는 데 쓴다)"""
    rows = db.execute(
        select(Message, User.name)
        .join(User, User.id == Message.user_id)
        .where(Message.group_id == group_id, Message.id > after_id)
        .order_by(Message.id)
        .limit(limit)
    )
    return [(m, name) for m, name in rows]


def list_recent(
    db: Session, group_id: str, limit: int, before_id: int | None = None
) -> list[tuple[Message, str]]:
    """가장 최근 limit 개(before_id 가 있으면 id < before_id 중)를 오래된 순으로."""
    stmt = (
        select(Message, User.name)
        .join(User, User.id == Message.user_id)
        .where(Message.group_id == group_id)
    )
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    rows = db.execute(stmt.order_by(Message.id.desc()).limit(limit)).all()
    return [(m, name) for m, name in reversed(rows)]
