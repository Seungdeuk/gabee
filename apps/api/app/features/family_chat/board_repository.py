"""게시판 기록의 DB 접근. 공지를 올릴 때마다 기록하고(같은 방의 같은 메시지는 한 줄), 목록은 (올린 시각, id) 키셋으로 최신순으로 읽는다."""

from datetime import UTC, datetime

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.features.family_group.models import User

from .models import ChatBoardPost, ChatPinnedMessage, Message


def upsert_post(
    db: Session, group_id: str, room_id: str, message_id: int, user_id: str, text: str
) -> ChatBoardPost:
    """공지로 올린 기록을 남긴다(commit 하지 않는다). 같은 방의 같은 메시지가 이미 있으면 올린 사람·시각·본문을 새로 고쳐 최신으로 올린다."""
    post = db.scalar(
        select(ChatBoardPost).where(
            ChatBoardPost.room_id == room_id, ChatBoardPost.message_id == message_id
        )
    )
    now = datetime.now(UTC)
    if post is not None:
        post.posted_by, post.posted_at, post.text = user_id, now, text
        return post
    post = ChatBoardPost(
        group_id=group_id,
        room_id=room_id,
        message_id=message_id,
        posted_by=user_id,
        posted_at=now,
        text=text,
    )
    try:
        with db.begin_nested():
            db.add(post)
            db.flush()
    except IntegrityError:  # 겹친 요청이 먼저 만들었다
        return db.scalar(
            select(ChatBoardPost).where(
                ChatBoardPost.room_id == room_id, ChatBoardPost.message_id == message_id
            )
        )
    return post


def has_post(db: Session, room_id: str, message_id: int) -> bool:
    return (
        db.scalar(
            select(ChatBoardPost.id).where(
                ChatBoardPost.room_id == room_id, ChatBoardPost.message_id == message_id
            )
        )
        is not None
    )


def get_post(db: Session, room_id: str, post_id: str) -> ChatBoardPost | None:
    return db.scalar(
        select(ChatBoardPost).where(ChatBoardPost.room_id == room_id, ChatBoardPost.id == post_id)
    )


def delete_post(db: Session, post: ChatBoardPost) -> None:
    """글 한 줄을 지운다(commit 하지 않는다)."""
    db.execute(delete(ChatBoardPost).where(ChatBoardPost.id == post.id))


def list_page(
    db: Session,
    room_id: str,
    limit: int,
    before: tuple[datetime, str] | None,
) -> list[tuple[ChatBoardPost, Message, str, str, bool]]:
    """글 + 원본 메시지 + 원본을 쓴 사람 이름 + 올린 사람 이름 + 지금 공지인지. 최신순으로 limit+1 개(다음 쪽이 있는지 알려고 하나 더)."""
    author = aliased(User)
    poster = aliased(User)
    stmt = (
        select(
            ChatBoardPost,
            Message,
            author.name,
            poster.name,
            select(ChatPinnedMessage.id)
            .where(
                ChatPinnedMessage.room_id == ChatBoardPost.room_id,
                ChatPinnedMessage.message_id == ChatBoardPost.message_id,
            )
            .exists(),
        )
        .join(Message, Message.id == ChatBoardPost.message_id)
        .join(author, author.id == Message.user_id)
        .join(poster, poster.id == ChatBoardPost.posted_by)
        .where(ChatBoardPost.room_id == room_id)
    )
    if before is not None:
        at, post_id = before
        stmt = stmt.where(
            or_(
                ChatBoardPost.posted_at < at,
                and_(ChatBoardPost.posted_at == at, ChatBoardPost.id < post_id),
            )
        )
    rows = db.execute(
        stmt.order_by(ChatBoardPost.posted_at.desc(), ChatBoardPost.id.desc()).limit(limit + 1)
    )
    return [(p, m, a, b, bool(cur)) for p, m, a, b, cur in rows]
