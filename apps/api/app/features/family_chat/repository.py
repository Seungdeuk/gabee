from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember, User

from .models import ChatReadState, Message

UNREAD_CAP = 1000  # 안 읽은 수를 세는 상한(앱이 99+ 로 줄여 보여준다)


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


def list_recent(
    db: Session, group_id: str, limit: int, before_id: int | None = None
) -> list[tuple[Message, str]]:
    """가장 최근 limit 개(before_id 가 있으면 id < before_id 중)를 오래된 순으로."""
    stmt = (
        select(Message, User.name)
        .join(User, User.id == Message.user_id)
        .where(Message.group_id == group_id)
    )
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    rows = db.execute(stmt.order_by(Message.id.desc()).limit(limit)).all()
    return [(m, name) for m, name in reversed(rows)]


def message_in_group(db: Session, group_id: str, message_id: int) -> bool:
    """message_id 가 이 그룹의 실제 메시지인지."""
    found = db.scalar(
        select(Message.id).where(Message.group_id == group_id, Message.id == message_id)
    )
    return found is not None


def _get_state(db: Session, group_id: str, user_id: str) -> ChatReadState | None:
    return db.get(ChatReadState, (group_id, user_id))


def _join_baseline():
    """읽음 기록이 없는 구성원의 기준선: 합류 시점(joined_at) 이하의 마지막 메시지 id(없으면 0).
    저장하지 않고 조회할 때 계산한다. joined_at 이 null 이면 비교가 거짓이라 0 이 된다."""
    return (
        select(func.max(Message.id))
        .where(
            Message.group_id == GroupMember.group_id,
            Message.created_at <= GroupMember.joined_at,
        )
        .correlate(GroupMember)
        .scalar_subquery()
    )


def get_last_read(db: Session, group_id: str, user_id: str) -> int:
    """기록된 읽음 위치와 합류 시점 기준선 중 큰 값."""
    row = db.execute(
        select(ChatReadState.last_read_message_id, _join_baseline())
        .select_from(GroupMember)
        .outerjoin(
            ChatReadState,
            (ChatReadState.group_id == GroupMember.group_id)
            & (ChatReadState.user_id == GroupMember.user_id),
        )
        .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
    ).first()
    if row is None:  # 구성원이 아니면 기준선이 없다
        return _get_state_value(db, group_id, user_id)
    last, base = row
    return max(last or 0, base or 0)


def _get_state_value(db: Session, group_id: str, user_id: str) -> int:
    return (
        db.scalar(
            select(ChatReadState.last_read_message_id).where(
                ChatReadState.group_id == group_id, ChatReadState.user_id == user_id
            )
        )
        or 0
    )


def advance_read(db: Session, group_id: str, user_id: str, message_id: int) -> int:
    """읽음 위치를 message_id 로 올린다(더 작거나 같으면 그대로). 현재 위치를 돌려준다.
    최초 저장이 동시에 겹쳐 기본키가 충돌하면 다시 읽어 갱신한다."""
    now = datetime.now(UTC)
    if _get_state(db, group_id, user_id) is None:
        try:
            db.add(
                ChatReadState(
                    group_id=group_id,
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
        update(ChatReadState)
        .where(
            ChatReadState.group_id == group_id,
            ChatReadState.user_id == user_id,
            ChatReadState.last_read_message_id < message_id,
        )
        .values(last_read_message_id=message_id, updated_at=now)
    )
    db.commit()
    return _get_state_value(db, group_id, user_id)


def read_states(db: Session, group_id: str) -> list[tuple[str, int]]:
    """현재 구성원 전원의 (user_id, 읽은 위치). 기록이 없으면 합류 시점 기준선(한 번의 쿼리)."""
    rows = db.execute(
        select(GroupMember.user_id, ChatReadState.last_read_message_id, _join_baseline())
        .outerjoin(
            ChatReadState,
            (ChatReadState.group_id == GroupMember.group_id)
            & (ChatReadState.user_id == GroupMember.user_id),
        )
        .where(GroupMember.group_id == group_id)
        .order_by(GroupMember.joined_at, GroupMember.user_id)
    )
    return [(uid, max(last or 0, base or 0)) for uid, last, base in rows]


def count_unread(db: Session, group_id: str, user_id: str, last_read: int) -> int:
    """last_read 이후 다른 사람이 보낸 메시지 수(UNREAD_CAP 에서 자른다)."""
    capped = (
        select(Message.id)
        .where(
            Message.group_id == group_id,
            Message.id > last_read,
            Message.user_id != user_id,
        )
        .limit(UNREAD_CAP)
        .subquery()
    )
    return db.scalar(select(func.count()).select_from(capped)) or 0
