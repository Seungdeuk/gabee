from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember, User

from .models import DIRECT, FAMILY, ChatRoom, ChatRoomMember, ChatRoomRead, Message

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


def last_message(db: Session, room: ChatRoom) -> tuple[Message, str] | None:
    rows = list_recent(db, room, 1)
    return rows[0] if rows else None


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
