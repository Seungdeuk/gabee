from sqlalchemy.orm import Session

from app.features.family_group.models import User

from . import repository as repo
from .models import Message
from .schemas import MessageOut


def _out(m: Message, user_name: str) -> MessageOut:
    return MessageOut(
        id=m.id, user_id=m.user_id, user_name=user_name, text=m.text, created_at=m.created_at
    )


def post(db: Session, user: User, group_id: str, text: str) -> MessageOut:
    return _out(
        repo.add(db, Message(group_id=group_id, user_id=user.id, text=text.strip())), user.name
    )


def list_messages(
    db: Session, group_id: str, after_id: int = 0, limit: int = 100
) -> list[MessageOut]:
    return [_out(m, name) for m, name in repo.list_after(db, group_id, after_id, limit)]
