from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.errors import bad_request, not_found

from . import repository as repo
from .models import FAMILY, ChatRoom, Message
from .schemas import MessageOut, ReadPosition, ReadStateOut, RoomOut, UnreadOut


def _out(m: Message, user_name: str) -> MessageOut:
    return MessageOut(
        id=m.id, user_id=m.user_id, user_name=user_name, text=m.text, created_at=m.created_at
    )


def resolve_room(db: Session, user: User, group_id: str, room_id: str | None) -> ChatRoom:
    """요청한 방을 찾는다. room_id 가 없으면 가족 전체방. 다른 가족의 방이거나 내가 참여자가 아닌
    1:1 방은 존재 여부를 숨기려고 모두 같은 404 로 답한다."""
    if room_id is None:
        return repo.get_family_room(db, group_id)
    room = repo.get_room(db, room_id)
    if room is None or room.group_id != group_id:
        raise not_found("대화방")
    if room.kind != FAMILY and not repo.is_room_member(db, room.id, user.id):
        raise not_found("대화방")
    return room


def post(
    db: Session, user: User, group_id: str, text: str, room_id: str | None = None
) -> MessageOut:
    room = resolve_room(db, user, group_id, room_id)
    message = repo.add(
        db, Message(group_id=group_id, room_id=room.id, user_id=user.id, text=text.strip())
    )
    out = _out(message, user.name)
    repo.advance_read(db, room.id, user.id, message.id)  # 내가 보낸 메시지는 읽은 것으로
    return out


def list_messages(
    db: Session,
    user: User,
    group_id: str,
    after_id: int = 0,
    limit: int = 100,
    latest: bool = False,
    before_id: int | None = None,
    room_id: str | None = None,
) -> list[MessageOut]:
    """latest·before_id·after_id(>0) 는 하나만 쓸 수 있다. 모두 없으면 가장 오래된 것부터."""
    if sum([latest, before_id is not None, after_id > 0]) > 1:
        raise bad_request("invalid_range", "latest, before_id, after_id 는 함께 쓸 수 없어요")
    room = resolve_room(db, user, group_id, room_id)
    if latest or before_id is not None:
        rows = repo.list_recent(db, room, limit, before_id)
    else:
        rows = repo.list_after(db, room, after_id, limit)
    return [_out(m, name) for m, name in rows]


def mark_read(
    db: Session, user: User, group_id: str, message_id: int, room_id: str | None = None
) -> ReadPosition:
    """내 읽음 위치를 올린다(앞으로만). 이 방의 메시지가 아니면 거절한다."""
    room = resolve_room(db, user, group_id, room_id)
    if not repo.message_in_room(db, room, message_id):
        raise bad_request("invalid_message", "이 대화방의 메시지가 아니에요")
    return ReadPosition(last_read_message_id=repo.advance_read(db, room.id, user.id, message_id))


def read_states(
    db: Session, user: User, group_id: str, room_id: str | None = None
) -> list[ReadStateOut]:
    room = resolve_room(db, user, group_id, room_id)
    return [
        ReadStateOut(user_id=uid, last_read_message_id=last)
        for uid, last in repo.read_states(db, room)
    ]


def unread(db: Session, user: User, group_id: str, room_id: str | None = None) -> UnreadOut:
    room = resolve_room(db, user, group_id, room_id)
    last = repo.get_last_read(db, room, user.id)
    return UnreadOut(unread=repo.count_unread(db, room, user.id, last), last_read_message_id=last)


# ── 대화방 목록·1:1 방 ────────────────────────────────


def _family_room_out(db: Session, user: User, room: ChatRoom) -> RoomOut:
    last = repo.last_message(db, room)
    unread_count = repo.count_unread(db, room, user.id, repo.get_last_read(db, room, user.id))
    return RoomOut(
        id=room.id,
        kind=room.kind,
        peer_user_id=None,
        last_message=_out(*last) if last else None,
        unread=unread_count,
    )


def _direct_room_out(room: ChatRoom, summary) -> RoomOut:
    last, unread_count, peer = summary
    return RoomOut(
        id=room.id,
        kind=room.kind,
        peer_user_id=peer,
        last_message=_out(*last) if last else None,
        unread=unread_count,
    )


def list_rooms(db: Session, user: User, group_id: str) -> list[RoomOut]:
    """가족 전체방(맨 위)과 내가 참여한 1:1 방(최근 메시지 순). 1:1 방 수와 상관없이 쿼리 수는 일정하다."""
    family = repo.get_family_room(db, group_id)
    rooms = repo.my_direct_rooms(db, group_id, user.id)
    summary = repo.rooms_summary(db, user.id, rooms)
    directs = [_direct_room_out(r, summary[r.id]) for r in rooms]
    directs.sort(key=lambda r: r.last_message.id if r.last_message else 0, reverse=True)
    return [_family_room_out(db, user, family), *directs]


def open_direct_room(db: Session, user: User, group_id: str, peer_id: str) -> RoomOut:
    """같은 가족 구성원과의 1:1 방을 돌려준다(없으면 만든다). 같은 두 사람의 방은 하나뿐이다."""
    if peer_id == user.id:
        raise bad_request("invalid_member", "자기 자신과는 1:1 대화를 할 수 없어요")
    if not repo.is_group_member(db, group_id, peer_id):
        raise bad_request("invalid_member", "같은 가족 구성원이 아니에요")
    key = ":".join(sorted([user.id, peer_id]))
    room = repo.get_direct_room(db, group_id, key) or repo.create_direct_room(
        db, group_id, key, [user.id, peer_id]
    )
    return _direct_room_out(room, repo.rooms_summary(db, user.id, [room])[room.id])
