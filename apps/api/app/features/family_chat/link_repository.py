"""메시지-일정·할 일 연결의 DB 접근. 모든 조회·삭제에 room_id(이미 권한 확인을 거친 방) 조건을 SQL 에 넣는다.
원본 메시지 본문은 복사하지 않고 조회할 때 join 으로만 가져온다."""

from datetime import UTC, date, datetime, time

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.features.family_group.models import User

from .models import ChatMessageLink, ChatRoom, Message

MAX_LINKS = 200  # 방당 최대 연결 수


def lock_room(db: Session, room_id: str) -> None:
    """같은 방의 연결 변경을 직렬화한다. PostgreSQL 은 방 행을 잠그고(SELECT ... FOR UPDATE), SQLite 는 무시된다."""
    db.execute(
        select(ChatRoom.id).where(ChatRoom.id == room_id).with_for_update(key_share=True)
    ).first()


def user_name(db: Session, user_id: str) -> str:
    return db.scalar(select(User.name).where(User.id == user_id)) or ""


def count_in_room(db: Session, room_id: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(ChatMessageLink)
            .where(ChatMessageLink.room_id == room_id)
        )
        or 0
    )


def get_existing(
    db: Session, room_id: str, message_id: int, kind: str, target_id: str
) -> ChatMessageLink | None:
    return db.scalar(
        select(ChatMessageLink).where(
            ChatMessageLink.room_id == room_id,
            ChatMessageLink.message_id == message_id,
            ChatMessageLink.kind == kind,
            ChatMessageLink.target_id == target_id,
        )
    )


def get_in_room(db: Session, room_id: str, link_id: str) -> ChatMessageLink | None:
    return db.scalar(
        select(ChatMessageLink).where(
            ChatMessageLink.room_id == room_id, ChatMessageLink.id == link_id
        )
    )


def add_link(
    db: Session,
    group_id: str,
    room_id: str,
    message_id: int,
    kind: str,
    target_id: str,
    title: str,
    on_date: date | None,
    at_time: time | None,
    user_id: str,
) -> ChatMessageLink | None:
    """연결을 추가한다(commit 하지 않는다). 같은 연결이 이미 있으면(유니크 충돌) None."""
    link = ChatMessageLink(
        group_id=group_id,
        room_id=room_id,
        message_id=message_id,
        kind=kind,
        target_id=target_id,
        title=title,
        date=on_date,
        time=at_time,
        created_by=user_id,
        created_at=datetime.now(UTC),
    )
    try:
        with db.begin_nested():
            db.add(link)
            db.flush()
    except IntegrityError:
        return None
    return link


def delete_link(db: Session, room_id: str, link_id: str) -> None:
    """연결을 지운다(commit 하지 않는다)."""
    db.execute(
        delete(ChatMessageLink).where(
            ChatMessageLink.room_id == room_id, ChatMessageLink.id == link_id
        )
    )


def link_rows(
    db: Session,
    room_id: str,
    limit: int,
    kind: str | None = None,
    target_id: str | None = None,
    link_id: str | None = None,
) -> list[tuple[ChatMessageLink, Message, str, str]]:
    """연결 + 원본 메시지 + 등록한 사람 이름 + 메시지를 쓴 사람 이름. 최신순(시각이 같으면 id 큰 쪽)."""
    author = aliased(User)
    creator = aliased(User)
    stmt = (
        select(ChatMessageLink, Message, creator.name, author.name)
        .join(Message, Message.id == ChatMessageLink.message_id)
        .join(creator, creator.id == ChatMessageLink.created_by)
        .join(author, author.id == Message.user_id)
        .where(ChatMessageLink.room_id == room_id)
    )
    if kind is not None:
        stmt = stmt.where(ChatMessageLink.kind == kind)
    if target_id is not None:
        stmt = stmt.where(ChatMessageLink.target_id == target_id)
    if link_id is not None:
        stmt = stmt.where(ChatMessageLink.id == link_id)
    rows = db.execute(
        stmt.order_by(ChatMessageLink.created_at.desc(), ChatMessageLink.id.desc()).limit(limit)
    )
    return [(link, m, c, a) for link, m, c, a in rows]
