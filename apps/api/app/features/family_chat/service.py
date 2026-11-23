from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared import chat_library, group_purge, member_exit
from app.shared.errors import ApiError, bad_request, not_found
from app.shared.schema import monitor

from . import chat_push
from . import repository as repo
from .models import (
    ASSISTANT_USER_ID,
    DIRECT,
    FAMILY,
    ChatRoom,
    Message,
    MessageAttachment,
    MessageShare,
)
from .schemas import (
    AttachmentOut,
    MessageOut,
    MuteOut,
    ReactionOut,
    ReadPosition,
    ReadStateOut,
    ReplyOut,
    RoomOut,
    ShareOut,
    UnreadOut,
)


def _utc(value: datetime | None) -> datetime | None:
    """시간대 없는 값(SQLite)은 UTC 로 보고 시간대를 붙인다(응답은 항상 시간대가 있는 UTC)."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _attachment_out(a: MessageAttachment, in_library: bool = False) -> AttachmentOut:
    if a.kind == "file":
        return AttachmentOut(
            id=a.id,
            kind="file",
            url=f"/family-chat/files/{a.id}",
            filename=a.filename,
            size_bytes=a.size_bytes,
            content_type=a.content_type,
        )
    return AttachmentOut(
        id=a.id,
        kind="image",
        url=f"/family-chat/photos/{a.id}",
        thumb_url=f"/family-chat/photos/{a.id}?size=thumb",
        width=a.width,
        height=a.height,
        batch_id=a.batch_id,
        size_bytes=a.size_bytes,
        in_library=in_library,
        taken_at=_utc(a.taken_at),
    )


PREVIEW_CHARS = 40  # 답장 미리보기 글자 수
REACTION_ORDER = ("\u2764\ufe0f", "👍", "😂", "😮", "😢", "🙏")  # 허용 이모지(표시 순서)


def reply_out(parent: tuple[Message, str, str | None]) -> ReplyOut:
    """원본 메시지(저장소가 모은 (메시지, 이름, 첨부 종류))를 미리보기로. 지운 원본은 내용 없이 deleted 만."""
    m, name, kind = parent
    deleted = m.deleted_at is not None
    return ReplyOut(
        id=m.id,
        user_name=name,
        text="" if deleted else m.text[:PREVIEW_CHARS],
        deleted=deleted,
        has_attachment=kind is not None and not deleted,
        attachment_kind=None if deleted else kind,
    )


def message_out(
    m: Message,
    user_name: str,
    attachment: MessageAttachment | None = None,
    reply: ReplyOut | None = None,
    reactions: list[ReactionOut] | None = None,
    in_library: bool = False,
    share: MessageShare | None = None,
) -> MessageOut:
    deleted = m.deleted_at is not None
    return MessageOut(
        id=m.id,
        user_id=m.user_id,
        user_name=user_name,
        text="" if deleted else m.text,
        created_at=m.created_at,
        attachment=_attachment_out(attachment, in_library) if attachment and not deleted else None,
        is_assistant=m.user_id == ASSISTANT_USER_ID,
        reply_to=None if deleted else reply,  # 지운 메시지는 답장 표시도 내용도 남기지 않는다
        reactions=[] if deleted else (reactions or []),
        share=ShareOut(kind=share.kind, payload=share.payload) if share and not deleted else None,
        deleted=deleted,
    )


def reaction_outs(summary: list[tuple[str, int, bool]] | None) -> list[ReactionOut]:
    """집계를 많은 순(같으면 허용 목록 순서)으로."""
    order = {emoji: i for i, emoji in enumerate(REACTION_ORDER)}
    ranked = sorted(summary or [], key=lambda r: (-r[1], order.get(r[0], len(order))))
    return [ReactionOut(emoji=e, count=n, mine=mine) for e, n, mine in ranked]


def _outs(
    db: Session, room: ChatRoom, rows: list[tuple[Message, str]], viewer_id: str
) -> list[MessageOut]:
    """메시지들을 응답 모양으로(첨부·답장 원본·반응은 각각 한 번의 쿼리로 모아 붙인다)."""
    attachments = repo.attachments_for(db, [m.id for m, _ in rows])
    parents = repo.reply_parents(db, room, [m for m, _ in rows])
    reactions = repo.reaction_summary(
        db, [m.id for m, _ in rows if m.deleted_at is None], viewer_id
    )
    saved = chat_library.registered_ids(
        db, room.group_id, [a.id for a in attachments.values() if a.kind == "image"]
    )
    # 공유 카드 테이블이 아직 없는 DB(공용 DB 반영 전)에서도 메시지 목록은 열린다: 카드 내용만 빠지고 고정 문구는 그대로 보인다
    shares = (
        repo.shares_for(db, [m.id for m, _ in rows if m.deleted_at is None])
        if share_table_ready()
        else {}
    )
    return [
        message_out(
            m,
            name,
            attachments.get(m.id),
            reply_out(parents[m.reply_to_id]) if m.reply_to_id in parents else None,
            reaction_outs(reactions.get(m.id)),
            m.id in attachments and attachments[m.id].id in saved,
            shares.get(m.id),
        )
        for m, name in rows
    ]


def share_table_ready() -> bool:
    """공유 카드 테이블이 이 DB 에 준비됐는지(준비 안 됐으면 카드 내용을 읽거나 지우지 않는다)."""
    return monitor.status().feature_ready("chat_share")


def message_view(
    db: Session, room: ChatRoom, found: tuple[Message, str], viewer_id: str
) -> MessageOut:
    """메시지 하나를 목록과 같은 모양(첨부·답장·반응 포함)으로."""
    return _outs(db, room, [found], viewer_id)[0]


LEFT_PREFIX = "left:"  # 한 사람이 나간 1:1 방의 direct_key 는 "left:<나간 사람 id>:<방 id>" 로 바뀐다(같은 두 사람의 새 방을 만들 수 있게 짝 키를 비운다)


def left_by(room: ChatRoom) -> str | None:
    """1:1 방에서 방을 나간 사람의 id(나간 사람이 없으면 None). 이 방은 남은 사람이 읽기만 할 수 있다."""
    key = room.direct_key or ""
    if room.kind != DIRECT or not key.startswith(LEFT_PREFIX):
        return None
    return key.split(":")[1] or None


def ensure_can_send(room: ChatRoom) -> None:
    """상대가 나간 1:1 방에는 새 메시지를 보낼 수 없다(409 peer_left_room)."""
    if left_by(room) is not None:
        raise ApiError(409, "peer_left_room", "상대방이 나가서 메시지를 보낼 수 없어요")


def leave_room(db: Session, user: User, group_id: str, room_id: str) -> None:
    """1:1 방을 나간다. 내 목록에서만 사라지고 상대는 기록을 그대로 갖는다(방은 읽기 전용이 된다). 둘 다 나가면 방의 모든 데이터와
    사진·문서 파일을 지운다(되돌릴 수 없다). 가족 전체방은 나갈 수 없다(400). 내 방이 아니거나 이미 나갔으면 404."""
    room = resolve_room(db, user, group_id, room_id)
    if room.kind == FAMILY:
        raise bad_request("cannot_leave_family_room", "가족 전체방은 나갈 수 없어요")
    repo.lock_room(db, room.id)  # 두 사람이 동시에 나가도 마지막 사람이 방을 지운다
    if not repo.is_room_member(db, room.id, user.id):
        raise not_found("대화방")
    try:
        files = _exit_direct_room(db, room, user.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    group_purge.purge_files(files)


def _exit_direct_room(db: Session, room: ChatRoom, user_id: str) -> list[Path]:
    """잠근 1:1 방에서 한 사람의 참여를 지운다(커밋은 부르는 쪽). 남은 사람이 있으면 방을 읽기 전용으로 바꾸고,
    아무도 없으면 방의 모든 데이터를 지운다(지울 디스크 파일 경로를 돌려준다)."""
    repo.remove_room_member(db, room.id, user_id)
    if repo.count_room_members(db, room.id) == 0:
        return group_purge.purge_room(db, room.id)
    room.direct_key = f"{LEFT_PREFIX}{user_id}:{room.id}"
    return []


def leave_direct_rooms_of_member(db: Session, group_id: str, user_id: str) -> list[Path]:
    """가족을 나가는 사람의 1:1 방 참여를 모두 지운다(되돌릴 수 없다: 다시 가입해도 옛 방은 이어지지 않는다). 커밋은 부르는 쪽.
    방은 id 순으로 잠가, 두 사람이 서로의 방을 동시에 정리해도 잠금 순서가 같아 교착이 생기지 않는다.
    이 DB 에 소통 테이블이 아직 없으면(코드가 DB 보다 먼저 배포) 지울 방도 없으니 건너뛴다."""
    if not monitor.status().feature_ready("family_chat"):
        return []
    files: list[Path] = []
    for room_id in sorted(r.id for r in repo.my_direct_rooms(db, group_id, user_id)):
        repo.lock_room(db, room_id)
        room = repo.get_room(db, room_id)
        if room is None or not repo.is_room_member(db, room_id, user_id):
            continue  # 잠그는 사이 방이 지워졌거나 이미 처리됨
        files += _exit_direct_room(db, room, user_id)
    return files


member_exit.register(leave_direct_rooms_of_member)


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
    ensure_can_send(room)
    parent = None
    if reply_to_id is not None:
        found = repo.get_in_room(
            db, room, reply_to_id
        )  # 같은 방(같은 가족·내가 들어갈 수 있는 방)의 메시지만
        if found is None:
            raise bad_request("invalid_message", "이 대화방의 메시지가 아니에요")
        if found[0].deleted_at is not None:
            raise bad_request("reply_deleted", "지운 메시지에는 답장할 수 없어요")
        attached = repo.attachments_for(db, [found[0].id]).get(found[0].id)
        parent = (found[0], found[1], (attached.kind or "image") if attached else None)
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
    chat_push.notify_new_message(
        db, room, message
    )  # 받을 사람에게 고정 문구 푸시(실패해도 전송은 그대로)
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
        return _outs(db, room, [*before, center, *after], user.id)
    limit = 100 if limit is None else limit
    if latest or before_id is not None:
        rows = repo.list_recent(db, room, limit, before_id)
    else:
        rows = repo.list_after(db, room, after_id, limit)
    return _outs(db, room, rows, user.id)


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
    muted: bool = False,
) -> RoomOut:
    left = left_by(room)
    return RoomOut(
        id=room.id,
        kind=room.kind,
        peer_user_id=peer or left,
        peer_left=left is not None,
        last_message=message_out(last[0], last[1], attachments.get(last[0].id)) if last else None,
        unread=unread_count,
        muted=muted,
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
    muted = repo.muted_room_ids(db, user.id, [family.id, *(r.id for r in rooms)])
    directs = [
        _room_out(
            r, summary[r.id][0], summary[r.id][1], summary[r.id][2], attachments, r.id in muted
        )
        for r in rooms
    ]
    directs.sort(key=lambda r: r.last_message.id if r.last_message else 0, reverse=True)
    family_out = _room_out(
        family, family_last, family_unread, None, attachments, family.id in muted
    )
    return [family_out, *directs]


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
    muted = room.id in repo.muted_room_ids(db, user.id, [room.id])
    return _room_out(room, last, unread_count, peer, attachments, muted)


def set_room_muted(db: Session, user: User, group_id: str, room_id: str, muted: bool) -> MuteOut:
    """이 방의 알림을 나만 끄거나 켠다(멱등). 설정만 저장하고 읽지 않은 수에는 영향이 없다.
    볼 수 없는 방은 다른 방 API 와 같이 404 다."""
    room = resolve_room(db, user, group_id, room_id)
    repo.set_muted(db, room.id, user.id, muted)
    return MuteOut(room_id=room.id, muted=muted)
