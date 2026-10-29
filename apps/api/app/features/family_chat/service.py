from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.errors import bad_request, not_found

from . import repository as repo
from .models import ASSISTANT_USER_ID, FAMILY, ChatRoom, Message, MessageAttachment
from .schemas import (
    AttachmentOut,
    MessageOut,
    ReadPosition,
    ReadStateOut,
    ReplyOut,
    RoomOut,
    UnreadOut,
)


def _attachment_out(a: MessageAttachment) -> AttachmentOut:
    return AttachmentOut(
        id=a.id,
        kind="image",
        url=f"/family-chat/photos/{a.id}",
        thumb_url=f"/family-chat/photos/{a.id}?size=thumb",
        width=a.width,
        height=a.height,
    )


PREVIEW_CHARS = 40  # 답장 미리보기 글자 수


def reply_out(parent: tuple[Message, str, bool]) -> ReplyOut:
    """원본 메시지(저장소가 모은 (메시지, 이름, 사진 여부))를 미리보기로. 지운 원본은 내용 없이 deleted 만."""
    m, name, has_attachment = parent
    deleted = m.deleted_at is not None
    return ReplyOut(
        id=m.id,
        user_name=name,
        text="" if deleted else m.text[:PREVIEW_CHARS],
        deleted=deleted,
        has_attachment=has_attachment and not deleted,
    )


def message_out(
    m: Message,
    user_name: str,
    attachment: MessageAttachment | None = None,
    reply: ReplyOut | None = None,
) -> MessageOut:
    deleted = m.deleted_at is not None
    return MessageOut(
        id=m.id,
        user_id=m.user_id,
        user_name=user_name,
        text="" if deleted else m.text,
        created_at=m.created_at,
        attachment=_attachment_out(attachment) if attachment and not deleted else None,
        is_assistant=m.user_id == ASSISTANT_USER_ID,
        reply_to=None if deleted else reply,  # 지운 메시지는 답장 표시도 내용도 남기지 않는다
        deleted=deleted,
    )


def _outs(db: Session, room: ChatRoom, rows: list[tuple[Message, str]]) -> list[MessageOut]:
    """메시지들을 응답 모양으로(첨부는 한 번의 쿼리로 모아 붙인다)."""
    attachments = repo.attachments_for(db, [m.id for m, _ in rows])
    parents = repo.reply_parents(db, room, [m for m, _ in rows])
    return [
        message_out(
            m,
            name,
            attachments.get(m.id),
            reply_out(parents[m.reply_to_id]) if m.reply_to_id in parents else None,
        )
        for m, name in rows
    ]


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
    db: Session,
    user: User,
    group_id: str,
    text: str,
    room_id: str | None = None,
    reply_to_id: int | None = None,
) -> MessageOut:
    room = resolve_room(db, user, group_id, room_id)
    parent = None
    if reply_to_id is not None:
        found = repo.get_in_room(
            db, room, reply_to_id
        )  # 같은 방(같은 가족·내가 들어갈 수 있는 방)의 메시지만
        if found is None:
            raise bad_request("invalid_message", "이 대화방의 메시지가 아니에요")
        if found[0].deleted_at is not None:
            raise bad_request("reply_deleted", "지운 메시지에는 답장할 수 없어요")
        parent = (found[0], found[1], bool(repo.attachments_for(db, [found[0].id])))
    message = repo.add(
        db,
        Message(
            group_id=group_id,
            room_id=room.id,
            user_id=user.id,
            text=text.strip(),
            reply_to_id=reply_to_id,
        ),
    )
    out = message_out(message, user.name, None, reply_out(parent) if parent else None)
    repo.advance_read(db, room.id, user.id, message.id)  # 내가 보낸 메시지는 읽은 것으로
    return out


def list_messages(
    db: Session,
    user: User,
    group_id: str,
    after_id: int = 0,
    limit: int | None = None,
    latest: bool = False,
    before_id: int | None = None,
    room_id: str | None = None,
    around_id: int | None = None,
) -> list[MessageOut]:
    """latest·before_id·after_id(>0)·around_id 는 하나만 쓸 수 있다. 모두 없으면 가장 오래된 것부터.
    around_id 는 그 메시지와 앞뒤 limit//2 개(기본 limit 50)를 오래된 순으로 돌려준다."""
    if sum([latest, before_id is not None, after_id > 0, around_id is not None]) > 1:
        raise bad_request(
            "invalid_range", "latest, before_id, after_id, around_id 는 함께 쓸 수 없어요"
        )
    room = resolve_room(db, user, group_id, room_id)
    if around_id is not None:
        half = (50 if limit is None else limit) // 2
        center = repo.get_in_room(db, room, around_id)
        if center is None:
            raise bad_request("invalid_message", "이 대화방의 메시지가 아니에요")
        before = repo.list_recent(db, room, half, around_id) if half else []
        after = repo.list_after(db, room, around_id, half) if half else []
        return _outs(db, room, [*before, center, *after])
    limit = 100 if limit is None else limit
    if latest or before_id is not None:
        rows = repo.list_recent(db, room, limit, before_id)
    else:
        rows = repo.list_after(db, room, after_id, limit)
    return _outs(db, room, rows)


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


def _room_out(
    room: ChatRoom,
    last: tuple[Message, str] | None,
    unread_count: int,
    peer: str | None,
    attachments: dict[int, MessageAttachment],
) -> RoomOut:
    return RoomOut(
        id=room.id,
        kind=room.kind,
        peer_user_id=peer,
        last_message=message_out(last[0], last[1], attachments.get(last[0].id)) if last else None,
        unread=unread_count,
    )


def list_rooms(db: Session, user: User, group_id: str) -> list[RoomOut]:
    """가족 전체방(맨 위)과 내가 참여한 1:1 방(최근 메시지 순). 1:1 방 수와 상관없이 쿼리 수는 일정하다."""
    family = repo.get_family_room(db, group_id)
    rooms = repo.my_direct_rooms(db, group_id, user.id)
    summary = repo.rooms_summary(db, user.id, rooms)
    family_last = repo.last_message(db, family)
    family_unread = repo.count_unread(db, family, user.id, repo.get_last_read(db, family, user.id))
    lasts = [summary[r.id][0] for r in rooms if summary[r.id][0]] + (
        [family_last] if family_last else []
    )
    attachments = repo.attachments_for(db, [m.id for m, _ in lasts])
    directs = [
        _room_out(r, summary[r.id][0], summary[r.id][1], summary[r.id][2], attachments)
        for r in rooms
    ]
    directs.sort(key=lambda r: r.last_message.id if r.last_message else 0, reverse=True)
    return [_room_out(family, family_last, family_unread, None, attachments), *directs]


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
    last, unread_count, peer = repo.rooms_summary(db, user.id, [room])[room.id]
    attachments = repo.attachments_for(db, [last[0].id] if last else [])
    return _room_out(room, last, unread_count, peer, attachments)
