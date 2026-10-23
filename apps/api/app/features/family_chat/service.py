from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.errors import bad_request

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
    db: Session,
    group_id: str,
    after_id: int = 0,
    limit: int = 100,
    latest: bool = False,
    before_id: int | None = None,
) -> list[MessageOut]:
    """latest·before_id·after_id(>0) 는 하나만 쓸 수 있다. 모두 없으면 가장 오래된 것부터."""
    if sum([latest, before_id is not None, after_id > 0]) > 1:
        raise bad_request("invalid_range", "latest, before_id, after_id 는 함께 쓸 수 없어요")
    if latest or before_id is not None:
        rows = repo.list_recent(db, group_id, limit, before_id)
    else:
        rows = repo.list_after(db, group_id, after_id, limit)
    return [_out(m, name) for m, name in rows]
