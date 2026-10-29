"""고정 메시지의 DB 접근. 고정은 메시지를 가리키기만 하고, 메시지 본문은 조회할 때 join 으로만 가져온다."""

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.features.family_group.models import User

from .models import ChatPinHide, ChatPinnedMessage, ChatRoom, Message

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
    db: Session, group_id: str, room_id: str, message_id: int, user_id: str, text: str
) -> ChatPinnedMessage | None:
    """게시판에 올린다(commit 하지 않는다). 올릴 때의 본문(text)을 사본으로 저장한다. 같은 메시지가 이미 올라가 있으면 None."""
    pin = ChatPinnedMessage(
        group_id=group_id,
        room_id=room_id,
        message_id=message_id,
        pinned_by=user_id,
        pinned_at=datetime.now(UTC),
        text=text,
    )
    try:
        with db.begin_nested():
            db.add(pin)
            db.flush()
    except IntegrityError:
        return None
    return pin


def _delete_hides(db: Session, room_id: str, message_ids: list[int]) -> None:
    """내려가는 공지의 "나만 숨기기" 기록을 지운다(commit 하지 않는다)."""
    pin_ids = select(ChatPinnedMessage.id).where(
        ChatPinnedMessage.room_id == room_id, ChatPinnedMessage.message_id.in_(message_ids)
    )
    db.execute(delete(ChatPinHide).where(ChatPinHide.pin_id.in_(pin_ids)))


def remove_pins(db: Session, room_id: str, message_ids: list[int]) -> None:
    """고정을 지운다(commit 하지 않는다). 숨김 기록도 함께 지운다."""
    _delete_hides(db, room_id, message_ids)
    db.execute(
        delete(ChatPinnedMessage).where(
            ChatPinnedMessage.room_id == room_id, ChatPinnedMessage.message_id.in_(message_ids)
        )
    )


def delete_pin(db: Session, room_id: str, message_id: int) -> bool:
    """고정을 해제한다(본문 사본·숨김 기록도 함께 사라진다). 없었으면 False."""
    _delete_hides(db, room_id, [message_id])
    result = db.execute(
        delete(ChatPinnedMessage).where(
            ChatPinnedMessage.room_id == room_id, ChatPinnedMessage.message_id == message_id
        )
    )
    db.commit()
    return result.rowcount > 0


def set_hidden(db: Session, pin_id: str, user_id: str, hidden: bool) -> None:
    """이 공지를 나만 숨기거나(hidden=True) 다시 보이게 한다. 이미 그 상태여도 같은 결과(겹친 요청에도 오류 없음)."""
    if hidden:
        if db.get(ChatPinHide, (pin_id, user_id)) is None:
            try:
                with db.begin_nested():
                    db.add(ChatPinHide(pin_id=pin_id, user_id=user_id))
                    db.flush()
            except IntegrityError:
                pass  # 겹친 요청이 먼저 숨겼다
    else:
        db.execute(
            delete(ChatPinHide).where(ChatPinHide.pin_id == pin_id, ChatPinHide.user_id == user_id)
        )
    db.commit()


def pin_rows(
    db: Session, room_id: str, limit: int, viewer_id: str, message_id: int | None = None
) -> list[tuple[ChatPinnedMessage, Message, str, str, bool]]:
    """고정 + 메시지 + 쓴 사람 이름 + 고정한 사람 이름 + 내가 숨겼는지. 고정 시각 최신순."""
    author = aliased(User)
    pinner = aliased(User)
    stmt = (
        select(
            ChatPinnedMessage, Message, author.name, pinner.name, ChatPinHide.user_id.is_not(None)
        )
        .join(Message, Message.id == ChatPinnedMessage.message_id)
        .join(author, author.id == Message.user_id)
        .join(pinner, pinner.id == ChatPinnedMessage.pinned_by)
        .outerjoin(
            ChatPinHide,
            (ChatPinHide.pin_id == ChatPinnedMessage.id) & (ChatPinHide.user_id == viewer_id),
        )
        .where(ChatPinnedMessage.room_id == room_id)
    )
    if message_id is not None:
        stmt = stmt.where(ChatPinnedMessage.message_id == message_id)
    rows = db.execute(
        stmt.order_by(
            ChatPinnedMessage.pinned_at.desc(), ChatPinnedMessage.message_id.desc()
        ).limit(limit)
    )
    return [(p, m, a, b, bool(h)) for p, m, a, b, h in rows]


def is_hidden(db: Session, pin_id: str, user_id: str) -> bool:
    return db.get(ChatPinHide, (pin_id, user_id)) is not None
