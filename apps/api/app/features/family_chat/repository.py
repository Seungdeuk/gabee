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
