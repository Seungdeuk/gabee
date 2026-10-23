from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.errors import bad_request

from . import repository as repo
from .models import Message
from .schemas import MessageOut, ReadPosition, ReadStateOut, UnreadOut


def _out(m: Message, user_name: str) -> MessageOut:
    return MessageOut(
        id=m.id, user_id=m.user_id, user_name=user_name, text=m.text, created_at=m.created_at
    )


def post(db: Session, user: User, group_id: str, text: str) -> MessageOut:
    message = repo.add(db, Message(group_id=group_id, user_id=user.id, text=text.strip()))
    out = _out(message, user.name)
    repo.advance_read(db, group_id, user.id, message.id)  # 내가 보낸 메시지는 읽은 것으로
    return out


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


def mark_read(db: Session, user: User, group_id: str, message_id: int) -> ReadPosition:
    """내 읽음 위치를 올린다(앞으로만). 이 그룹의 메시지가 아니면 거절한다."""
    if not repo.message_in_group(db, group_id, message_id):
        raise bad_request("invalid_message", "이 대화방의 메시지가 아니에요")
    return ReadPosition(last_read_message_id=repo.advance_read(db, group_id, user.id, message_id))


def read_states(db: Session, group_id: str) -> list[ReadStateOut]:
    return [
        ReadStateOut(user_id=uid, last_read_message_id=last)
        for uid, last in repo.read_states(db, group_id)
    ]


def unread(db: Session, user: User, group_id: str) -> UnreadOut:
    last = repo.get_last_read(db, group_id, user.id)
    return UnreadOut(
        unread=repo.count_unread(db, group_id, user.id, last), last_read_message_id=last
    )
