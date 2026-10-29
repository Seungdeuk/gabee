"""메시지 반응 업무 규칙: 한 사람이 한 메시지에 하나(바꾸면 교체), 이모지 6개만, 방 접근 규칙은 조회와 같다."""

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.errors import bad_request, not_found

from . import repository as repo
from . import service
from .schemas import MessageOut

_VS16 = "\ufe0f"  # 이모지 표시 변형 문자(❤ 와 ❤️ 를 같은 것으로 본다)
_ALLOWED = {e.replace(_VS16, ""): e for e in service.REACTION_ORDER}


def _canonical(emoji: str) -> str:
    found = _ALLOWED.get(emoji.replace(_VS16, ""))
    if found is None:
        raise bad_request("invalid_reaction", "쓸 수 없는 반응이에요")
    return found


def _message(db: Session, user: User, group_id: str, message_id: int, room_id: str | None):
    room = service.resolve_room(db, user, group_id, room_id)
    found = repo.get_in_room(db, room, message_id)
    if found is None:
        raise not_found("메시지")
    return room, found


def react(
    db: Session,
    user: User,
    group_id: str,
    message_id: int,
    emoji: str,
    room_id: str | None = None,
) -> MessageOut:
    """내 반응을 정한다(이미 있으면 바꾼다, 같은 것이면 그대로). 지운 메시지에는 못 한다."""
    canonical = _canonical(emoji)
    room, found = _message(db, user, group_id, message_id, room_id)
    if found[0].deleted_at is not None:
        raise bad_request("message_deleted", "지운 메시지에는 반응할 수 없어요")
    repo.set_reaction(db, message_id, user.id, canonical)
    return service.message_view(db, room, found, user.id)


def unreact(
    db: Session, user: User, group_id: str, message_id: int, room_id: str | None = None
) -> MessageOut:
    """내 반응을 지운다(없어도 같은 결과)."""
    room, found = _message(db, user, group_id, message_id, room_id)
    repo.clear_reaction(db, message_id, user.id)
    return service.message_view(db, room, found, user.id)
