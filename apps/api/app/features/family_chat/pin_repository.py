"""고정 메시지의 DB 접근. 고정은 메시지를 가리키기만 하고, 메시지 본문은 조회할 때 join 으로만 가져온다."""

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.features.family_group.models import User

from .models import ChatPinnedMessage, ChatRoom, Message

MAX_PINS = 2  # 방당 최대 고정 수


def lock_room(db: Session, room_id: str) -> None:
    """같은 방의 고정 변경을 직렬화한다. PostgreSQL 은 방 행을 잠가(SELECT ... FOR UPDATE) 다른 요청이
    끝날 때까지 기다리게 하고, SQLite 는 FOR UPDATE 를 지원하지 않아 무시된다(쓰기가 원래 직렬이다)."""
    db.execute(
        select(ChatRoom.id).where(ChatRoom.id == room_id).with_for_update(key_share=True)
    ).first()


def user_name(db: Session, user_id: str) -> str:
    return db.scalar(select(User.name).where(User.id == user_id)) or ""


def pins_in_room(db: Session, room_id: str) -> list[ChatPinnedMessage]:
    """이 방의 고정을 최신순으로. 시각이 같으면 메시지 id 가 큰 쪽이 최신이다."""
    return list(
        db.scalars(
            select(ChatPinnedMessage)
            .where(ChatPinnedMessage.room_id == room_id)
            .order_by(ChatPinnedMessage.pinned_at.desc(), ChatPinnedMessage.message_id.desc())
        )
    )


def get_pin(db: Session, room_id: str, message_id: int) -> ChatPinnedMessage | None:
    return db.scalar(
        select(ChatPinnedMessage).where(
            ChatPinnedMessage.room_id == room_id, ChatPinnedMessage.message_id == message_id
        )
    )


def add_pin(
    db: Session, group_id: str, room_id: str, message_id: int, user_id: str
) -> ChatPinnedMessage | None:
    """고정을 추가한다(commit 하지 않는다). 같은 메시지가 이미 고정돼 있으면 None."""
    pin = ChatPinnedMessage(
        group_id=group_id,
        room_id=room_id,
        message_id=message_id,
        pinned_by=user_id,
        pinned_at=datetime.now(UTC),
    )
    try:
        with db.begin_nested():
            db.add(pin)
            db.flush()
    except IntegrityError:
        return None
    return pin


def remove_pins(db: Session, room_id: str, message_ids: list[int]) -> None:
    """고정을 지운다(commit 하지 않는다)."""
    db.execute(
        delete(ChatPinnedMessage).where(
            ChatPinnedMessage.room_id == room_id, ChatPinnedMessage.message_id.in_(message_ids)
        )
    )


def delete_pin(db: Session, room_id: str, message_id: int) -> bool:
    """고정을 해제한다. 없었으면 False."""
    result = db.execute(
        delete(ChatPinnedMessage).where(
            ChatPinnedMessage.room_id == room_id, ChatPinnedMessage.message_id == message_id
        )
    )
    db.commit()
    return result.rowcount > 0


def pin_rows(
    db: Session, room_id: str, limit: int, message_id: int | None = None
) -> list[tuple[ChatPinnedMessage, Message, str, str]]:
    """고정 + 메시지 + 쓴 사람 이름 + 고정한 사람 이름. 고정 시각 최신순."""
    author = aliased(User)
    pinner = aliased(User)
    stmt = (
        select(ChatPinnedMessage, Message, author.name, pinner.name)
        .join(Message, Message.id == ChatPinnedMessage.message_id)
        .join(author, author.id == Message.user_id)
        .join(pinner, pinner.id == ChatPinnedMessage.pinned_by)
        .where(ChatPinnedMessage.room_id == room_id)
    )
    if message_id is not None:
        stmt = stmt.where(ChatPinnedMessage.message_id == message_id)
    rows = db.execute(
        stmt.order_by(
            ChatPinnedMessage.pinned_at.desc(), ChatPinnedMessage.message_id.desc()
        ).limit(limit)
    )
    return [(p, m, a, b) for p, m, a, b in rows]
