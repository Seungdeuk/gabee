from datetime import UTC, datetime

from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember, User

from .models import (
    DIRECT,
    FAMILY,
    ChatRoom,
    ChatRoomMember,
    ChatRoomMute,
    ChatRoomRead,
    Message,
    MessageAttachment,
    MessageReaction,
)

UNREAD_CAP = 1000  # 안 읽은 수를 세는 상한(앱이 99+ 로 줄여 보여준다)


# ── 대화방 ──────────────────────────────────────────────


def family_messages(group_id: str):
    """가족 전체방 메시지 조건. 1:1 방 메시지는 들어오지 않는다(AI 분석도 이 조건만 쓴다).
    room_id 가 비어 있는 옛 메시지(배포 중 구 서버가 쓴 것 포함)는 가족 전체방으로 본다."""
    family_ids = select(ChatRoom.id).where(ChatRoom.group_id == group_id, ChatRoom.kind == FAMILY)
    return and_(
        Message.group_id == group_id,
        or_(Message.room_id.is_(None), Message.room_id.in_(family_ids)),
    )


def room_messages(room: ChatRoom):
    """이 방의 메시지 조건."""
    if room.kind == FAMILY:
        return and_(
            Message.group_id == room.group_id,
            or_(Message.room_id.is_(None), Message.room_id == room.id),
        )
    return Message.room_id == room.id


def get_family_room(db: Session, group_id: str) -> ChatRoom:
    """가족 전체방. 없으면 만든다(동시에 만들다 겹치면 먼저 만들어진 것을 쓴다)."""
    stmt = select(ChatRoom).where(ChatRoom.group_id == group_id, ChatRoom.kind == FAMILY)
    room = db.scalar(stmt)
    if room is not None:
        return room
    try:
        room = ChatRoom(group_id=group_id, kind=FAMILY)
        db.add(room)
        db.commit()
        return room
    except IntegrityError:
        db.rollback()
        return db.scalar(stmt)


def get_room(db: Session, room_id: str) -> ChatRoom | None:
    return db.get(ChatRoom, room_id)


def is_room_member(db: Session, room_id: str, user_id: str) -> bool:
    found = db.scalar(
        select(ChatRoomMember.user_id).where(
            ChatRoomMember.room_id == room_id, ChatRoomMember.user_id == user_id
        )
    )
    return found is not None


def is_group_member(db: Session, group_id: str, user_id: str) -> bool:
    found = db.scalar(
        select(GroupMember.user_id).where(
            GroupMember.group_id == group_id, GroupMember.user_id == user_id
        )
    )
    return found is not None


def get_direct_room(db: Session, group_id: str, direct_key: str) -> ChatRoom | None:
    return db.scalar(
        select(ChatRoom).where(ChatRoom.group_id == group_id, ChatRoom.direct_key == direct_key)
    )


def create_direct_room(
    db: Session, group_id: str, direct_key: str, user_ids: list[str]
) -> ChatRoom:
    """두 사람의 1:1 방을 만든다. 동시에 같은 방을 만들다 겹치면 먼저 만들어진 방을 돌려준다."""
    room = ChatRoom(group_id=group_id, kind=DIRECT, direct_key=direct_key)
    try:
        db.add(room)
        db.flush()
        db.add_all([ChatRoomMember(room_id=room.id, user_id=uid) for uid in user_ids])
        db.commit()
        return room
    except IntegrityError:
        db.rollback()
        return get_direct_room(db, group_id, direct_key)


def my_direct_rooms(db: Session, group_id: str, user_id: str) -> list[ChatRoom]:
    return list(
        db.scalars(
            select(ChatRoom)
            .join(ChatRoomMember, ChatRoomMember.room_id == ChatRoom.id)
            .where(
                ChatRoom.group_id == group_id,
                ChatRoom.kind == DIRECT,
                ChatRoomMember.user_id == user_id,
            )
            .order_by(ChatRoom.created_at, ChatRoom.id)
        )
    )


def peer_of(db: Session, room_id: str, user_id: str) -> str | None:
    return db.scalar(
        select(ChatRoomMember.user_id).where(
            ChatRoomMember.room_id == room_id, ChatRoomMember.user_id != user_id
        )
    )


# ── 메시지 ──────────────────────────────────────────────


def add(db: Session, message: Message) -> Message:
    db.add(message)
    db.commit()
    return message


def list_after(db: Session, room: ChatRoom, after_id: int, limit: int) -> list[tuple[Message, str]]:
    """after_id 보다 새로운 메시지를 오래된 순으로. (앱이 몇 초마다 새 메시지만 가져오는 데 쓴다)"""
    rows = db.execute(
        select(Message, User.name)
        .join(User, User.id == Message.user_id)
        .where(room_messages(room), Message.id > after_id)
        .order_by(Message.id)
        .limit(limit)
    )
    return [(m, name) for m, name in rows]


def list_recent(
    db: Session, room: ChatRoom, limit: int, before_id: int | None = None
) -> list[tuple[Message, str]]:
    """가장 최근 limit 개(before_id 가 있으면 id < before_id 중)를 오래된 순으로."""
    stmt = (
        select(Message, User.name).join(User, User.id == Message.user_id).where(room_messages(room))
    )
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    rows = db.execute(stmt.order_by(Message.id.desc()).limit(limit)).all()
    return [(m, name) for m, name in reversed(rows)]


def soft_delete(db: Session, message: Message, attachment: MessageAttachment | None) -> None:
    """메시지를 지운 것으로 표시하고 본문·첨부를 비운다(행은 남긴다). 파일 삭제는 호출하는 쪽이 DB 저장 뒤에 한다."""
    message.text = ""
    message.reply_to_id = None  # 지우면 어느 글에 답했는지도 남기지 않는다
    message.deleted_at = datetime.now(UTC)
    if attachment is not None:
        db.delete(attachment)
    db.execute(
        delete(MessageReaction).where(MessageReaction.message_id == message.id)
    )  # 반응도 남기지 않는다
    db.commit()


def deleted_since(db: Session, room: ChatRoom, since: datetime, limit: int = 200) -> list[int]:
    """since 이후(같은 시각 포함)에 지워진 이 방의 메시지 id 를 지운 순서대로."""
    rows = db.scalars(
        select(Message.id)
        .where(room_messages(room), Message.deleted_at.is_not(None), Message.deleted_at >= since)
        .order_by(Message.deleted_at, Message.id)
        .limit(limit)
    )
    return list(rows)


def reply_parents(
    db: Session, room: ChatRoom, messages: list[Message]
) -> dict[int, tuple[Message, str, str | None]]:
    """답장인 메시지들의 원본을 한 번에 모은다: 원본 id -> (원본, 보낸 사람 이름, 첨부 종류 image|file|None).
    원본도 같은 방(room_messages)에서만 찾는다 — 답장을 넣을 때의 방 검사가 빠진 잘못된 데이터가 있어도
    다른 방 메시지의 내용이 미리보기로 나가지 않게 하는 방어선이다.
    메시지 수와 상관없이 쿼리 수는 일정하다(원본 1번 + 첨부 1번)."""
    parent_ids = {m.reply_to_id for m in messages if m.reply_to_id is not None}
    if not parent_ids:
        return {}
    rows = db.execute(
        select(Message, User.name)
        .join(User, User.id == Message.user_id)
        .where(room_messages(room), Message.id.in_(parent_ids))
    ).all()
    attached = attachments_for(db, [m.id for m, _ in rows])
    return {
        m.id: (m, name, (attached[m.id].kind or "image") if m.id in attached else None)
        for m, name in rows
    }


def reaction_summary(
    db: Session, message_ids: list[int], viewer_id: str
) -> dict[int, list[tuple[str, int, bool]]]:
    """메시지별 반응 집계를 한 번에: 메시지 id -> [(이모지, 사람 수, 내가 눌렀는지)]. 메시지 수와 상관없이 쿼리 1번."""
    if not message_ids:
        return {}
    mine = case((MessageReaction.user_id == viewer_id, 1), else_=0)
    rows = db.execute(
        select(
            MessageReaction.message_id,
            MessageReaction.emoji,
            func.count(MessageReaction.user_id),
            func.max(mine),
        )
        .where(MessageReaction.message_id.in_(message_ids))
        .group_by(MessageReaction.message_id, MessageReaction.emoji)
    ).all()
    out: dict[int, list[tuple[str, int, bool]]] = {}
    for message_id, emoji, count, is_mine in rows:
        out.setdefault(message_id, []).append((emoji, count, bool(is_mine)))
    return out


def set_reaction(db: Session, message_id: int, user_id: str, emoji: str) -> None:
    """내 반응을 정한다(없으면 만들고 있으면 이모지를 바꾼다). 한 번의 upsert(INSERT … ON CONFLICT DO UPDATE)라서
    읽고 쓰는 사이에 같은 사람의 취소·다른 이모지 요청이 끼어들어도 오류 없이 마지막 요청대로 된다."""
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(
        insert(MessageReaction)
        .values(message_id=message_id, user_id=user_id, emoji=emoji, created_at=datetime.now(UTC))
        .on_conflict_do_update(
            index_elements=[MessageReaction.message_id, MessageReaction.user_id],
            set_={"emoji": emoji},
        )
    )
    db.commit()


def clear_message_reactions(db: Session, message_id: int) -> None:
    """이 메시지의 반응을 모두 지운다(메시지를 지울 때, 지운 뒤에 저장된 반응을 치울 때)."""
    db.execute(delete(MessageReaction).where(MessageReaction.message_id == message_id))
    db.commit()


def clear_reaction(db: Session, message_id: int, user_id: str) -> None:
    db.execute(
        delete(MessageReaction).where(
            MessageReaction.message_id == message_id, MessageReaction.user_id == user_id
        )
    )
    db.commit()


def last_message(db: Session, room: ChatRoom) -> tuple[Message, str] | None:
    rows = list_recent(db, room, 1)
    return rows[0] if rows else None


def get_in_room(db: Session, room: ChatRoom, message_id: int) -> tuple[Message, str] | None:
    """이 방의 메시지 하나와 보낸 사람 이름. 이 방의 메시지가 아니면 None."""
    row = db.execute(
        select(Message, User.name)
        .join(User, User.id == Message.user_id)
        .where(room_messages(room), Message.id == message_id)
    ).first()
    return (row[0], row[1]) if row else None


def message_in_room(db: Session, room: ChatRoom, message_id: int) -> bool:
    """message_id 가 이 방의 실제 메시지인지."""
    found = db.scalar(select(Message.id).where(room_messages(room), Message.id == message_id))
    return found is not None


# ── 읽음 ────────────────────────────────────────────────


def _get_state(db: Session, room_id: str, user_id: str) -> ChatRoomRead | None:
    return db.get(ChatRoomRead, (room_id, user_id))


def _join_baseline(room: ChatRoom):
    """(가족 전체방) 읽음 기록이 없는 구성원의 기준선: 합류 시점(joined_at) 이하의 마지막 메시지 id(없으면 0).
    저장하지 않고 조회할 때 계산한다. joined_at 이 null 이면 비교가 거짓이라 0 이 된다."""
    return (
        select(func.max(Message.id))
        .where(
            room_messages(room),  # 같은 가족의 1:1 방 메시지 id 는 기준선에 넣지 않는다
            Message.created_at <= GroupMember.joined_at,
        )
        .correlate(GroupMember)
        .scalar_subquery()
    )


def get_last_read(db: Session, room: ChatRoom, user_id: str) -> int:
    """기록된 읽음 위치(가족 전체방은 합류 시점 기준선과 비교해 큰 값)."""
    if room.kind != FAMILY:
        return _get_state_value(db, room.id, user_id)
    row = db.execute(
        select(ChatRoomRead.last_read_message_id, _join_baseline(room))
        .select_from(GroupMember)
        .outerjoin(
            ChatRoomRead,
            (ChatRoomRead.room_id == room.id) & (ChatRoomRead.user_id == GroupMember.user_id),
        )
        .where(GroupMember.group_id == room.group_id, GroupMember.user_id == user_id)
    ).first()
    if row is None:  # 구성원이 아니면 기준선이 없다
        return _get_state_value(db, room.id, user_id)
    last, base = row
    return max(last or 0, base or 0)


def _get_state_value(db: Session, room_id: str, user_id: str) -> int:
    return (
        db.scalar(
            select(ChatRoomRead.last_read_message_id).where(
                ChatRoomRead.room_id == room_id, ChatRoomRead.user_id == user_id
            )
        )
        or 0
    )


def advance_read(db: Session, room_id: str, user_id: str, message_id: int) -> int:
    """읽음 위치를 message_id 로 올린다(더 작거나 같으면 그대로). 현재 위치를 돌려준다.
    최초 저장이 동시에 겹쳐 기본키가 충돌하면 다시 읽어 갱신한다."""
    now = datetime.now(UTC)
    if _get_state(db, room_id, user_id) is None:
        try:
            db.add(
                ChatRoomRead(
                    room_id=room_id,
                    user_id=user_id,
                    last_read_message_id=message_id,
                    updated_at=now,
                )
            )
            db.commit()
            return message_id
        except IntegrityError:  # 다른 요청이 먼저 만들었다 - 아래 갱신으로 이어간다
            db.rollback()
    db.execute(
        update(ChatRoomRead)
        .where(
            ChatRoomRead.room_id == room_id,
            ChatRoomRead.user_id == user_id,
            ChatRoomRead.last_read_message_id < message_id,
        )
        .values(last_read_message_id=message_id, updated_at=now)
    )
    db.commit()
    return _get_state_value(db, room_id, user_id)


def read_states(db: Session, room: ChatRoom) -> list[tuple[str, int]]:
    """방 참여자 전원의 (user_id, 읽은 위치). 가족 전체방은 기록이 없으면 합류 시점 기준선(한 번의 쿼리)."""
    if room.kind == FAMILY:
        rows = db.execute(
            select(GroupMember.user_id, ChatRoomRead.last_read_message_id, _join_baseline(room))
            .outerjoin(
                ChatRoomRead,
                (ChatRoomRead.room_id == room.id) & (ChatRoomRead.user_id == GroupMember.user_id),
            )
            .where(GroupMember.group_id == room.group_id)
            .order_by(GroupMember.joined_at, GroupMember.user_id)
        )
        return [(uid, max(last or 0, base or 0)) for uid, last, base in rows]
    rows = db.execute(
        select(ChatRoomMember.user_id, ChatRoomRead.last_read_message_id)
        .outerjoin(
            ChatRoomRead,
            (ChatRoomRead.room_id == ChatRoomMember.room_id)
            & (ChatRoomRead.user_id == ChatRoomMember.user_id),
        )
        .where(ChatRoomMember.room_id == room.id)
        .order_by(ChatRoomMember.user_id)
    )
    return [(uid, last or 0) for uid, last in rows]


def count_unread(db: Session, room: ChatRoom, user_id: str, last_read: int) -> int:
    """last_read 이후 다른 사람이 보낸 메시지 수(UNREAD_CAP 에서 자른다)."""
    capped = (
        select(Message.id)
        .where(room_messages(room), Message.id > last_read, Message.user_id != user_id)
        .limit(UNREAD_CAP)
        .subquery()
    )
    return db.scalar(select(func.count()).select_from(capped)) or 0


def rooms_summary(
    db: Session, user_id: str, rooms: list[ChatRoom]
) -> dict[str, tuple[tuple[Message, str] | None, int, str | None]]:
    """1:1 방들의 (마지막 메시지, 안 읽은 수, 상대 user_id) 를 방 수와 상관없이 쿼리 몇 번으로 모은다."""
    ids = [r.id for r in rooms]
    if not ids:
        return {}
    last_ids = dict(
        db.execute(
            select(Message.room_id, func.max(Message.id))
            .where(Message.room_id.in_(ids))
            .group_by(Message.room_id)
        ).all()
    )
    last_by_id = {}
    if last_ids:
        rows = db.execute(
            select(Message, User.name)
            .join(User, User.id == Message.user_id)
            .where(Message.id.in_(list(last_ids.values())))
        )
        last_by_id = {m.room_id: (m, name) for m, name in rows}
    unread = dict(
        db.execute(
            select(Message.room_id, func.count(Message.id))
            .outerjoin(
                ChatRoomRead,
                (ChatRoomRead.room_id == Message.room_id) & (ChatRoomRead.user_id == user_id),
            )
            .where(
                Message.room_id.in_(ids),
                Message.user_id != user_id,
                Message.id > func.coalesce(ChatRoomRead.last_read_message_id, 0),
            )
            .group_by(Message.room_id)
        ).all()
    )
    peers = dict(
        db.execute(
            select(ChatRoomMember.room_id, ChatRoomMember.user_id).where(
                ChatRoomMember.room_id.in_(ids), ChatRoomMember.user_id != user_id
            )
        ).all()
    )
    return {
        rid: (last_by_id.get(rid), min(unread.get(rid, 0), UNREAD_CAP), peers.get(rid))
        for rid in ids
    }


def room_member_ids(db: Session, room: ChatRoom) -> list[str]:
    """이 방에 들어갈 수 있는 사람: 가족 전체방은 가족 구성원 전원, 1:1 은 참여자 두 사람."""
    if room.kind == FAMILY:
        stmt = select(GroupMember.user_id).where(GroupMember.group_id == room.group_id)
    else:  # 가족을 나간 사람의 1:1 방 참여 기록은 남아 있으니 지금도 이 가족인 사람만
        stmt = (
            select(ChatRoomMember.user_id)
            .join(
                GroupMember,
                and_(
                    GroupMember.user_id == ChatRoomMember.user_id,
                    GroupMember.group_id == room.group_id,
                ),
            )
            .where(ChatRoomMember.room_id == room.id)
        )
    return list(db.scalars(stmt))


def muted_user_ids(db: Session, room_id: str) -> set[str]:
    """이 방의 알림을 끈 사람들의 id."""
    return set(db.scalars(select(ChatRoomMute.user_id).where(ChatRoomMute.room_id == room_id)))


def earlier_batch_photo_exists(
    db: Session, room: ChatRoom, message: Message, batch_id: str, since: datetime
) -> bool:
    """같은 사람이 같은 방에 같은 묶음 번호로 since 이후에 이 메시지보다 먼저 올린 지우지 않은 사진이 있는지(묶음의 첫 사진이 아닌지).
    같은 번호를 오래 뒤에 다시 쓰는 경우를 새 묶음으로 보려고 기간을 둔다."""
    found = db.scalar(
        select(MessageAttachment.id)
        .join(Message, Message.id == MessageAttachment.message_id)
        .where(
            room_messages(room),
            Message.user_id == message.user_id,
            Message.id < message.id,
            Message.deleted_at.is_(None),
            Message.created_at >= since,
            MessageAttachment.batch_id == batch_id,
        )
        .limit(1)
    )
    return found is not None


def sent_since(db: Session, room: ChatRoom, message: Message, since: datetime) -> bool:
    """같은 사람이 같은 방에 이 메시지보다 먼저 since 이후에 보낸 지우지 않은 메시지가 있는지."""
    found = db.scalar(
        select(Message.id)
        .where(
            room_messages(room),
            Message.user_id == message.user_id,
            Message.id < message.id,
            Message.deleted_at.is_(None),
            Message.created_at >= since,
        )
        .limit(1)
    )
    return found is not None


def muted_room_ids(db: Session, user_id: str, room_ids: list[str]) -> set[str]:
    """이 방들 중 내가 알림을 끈 방의 id. 방 수와 상관없이 쿼리 한 번."""
    if not room_ids:
        return set()
    rows = db.execute(
        select(ChatRoomMute.room_id).where(
            ChatRoomMute.user_id == user_id, ChatRoomMute.room_id.in_(room_ids)
        )
    )
    return set(rows.scalars())


def set_muted(db: Session, room_id: str, user_id: str, muted: bool) -> None:
    """알림 끄기를 저장한다. 이미 그 상태여도 같은 결과(겹친 요청에도 오류 없음)."""
    if muted:
        if db.get(ChatRoomMute, (room_id, user_id)) is None:
            try:
                with db.begin_nested():
                    db.add(ChatRoomMute(room_id=room_id, user_id=user_id))
                    db.flush()
            except IntegrityError:
                pass  # 겹친 요청이 먼저 껐다
    else:
        db.execute(
            delete(ChatRoomMute).where(
                ChatRoomMute.room_id == room_id, ChatRoomMute.user_id == user_id
            )
        )
    db.commit()


# ── 첨부(사진) ───────────────────────────────────────────


def add_photo_message(
    db: Session, message: Message, attachment: MessageAttachment
) -> tuple[Message, MessageAttachment]:
    """사진 메시지와 첨부를 한 번에 저장한다(둘 다 되거나 둘 다 안 된다)."""
    try:
        db.add(message)
        db.flush()
        attachment.message_id = message.id
        db.add(attachment)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return message, attachment


def attachments_for(db: Session, message_ids: list[int]) -> dict[int, MessageAttachment]:
    """메시지 id 들의 첨부를 한 번의 쿼리로."""
    if not message_ids:
        return {}
    rows = db.scalars(
        select(MessageAttachment).where(MessageAttachment.message_id.in_(message_ids))
    )
    return {a.message_id: a for a in rows}


def get_attachment(db: Session, attachment_id: str) -> MessageAttachment | None:
    return db.get(MessageAttachment, attachment_id)
