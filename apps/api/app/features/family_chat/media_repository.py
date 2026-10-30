from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.features.family_group.models import User

from .models import ChatRoom, Message, MessageAttachment
from .repository import room_messages


def list_page(
    db: Session, room: ChatRoom, limit: int, before_id: int | None, kind: str | None = None
) -> list[tuple[MessageAttachment, Message, str]]:
    """이 방 메시지에 붙은 첨부를 메시지 id 최신순으로 limit+1 개(다음 쪽이 있는지 알려고 하나 더).
    방 조건은 메시지(room_messages) 기준이라 다른 방·다른 가족 첨부는 SQL 에서 걸러진다."""
    stmt = (
        select(MessageAttachment, Message, User.name)
        .join(Message, Message.id == MessageAttachment.message_id)
        .join(User, User.id == Message.user_id)
        .where(room_messages(room))
    )
    if kind is not None:  # 사진 모음에 문서가 섞이지 않게 SQL 에서 거른다
        stmt = stmt.where(MessageAttachment.kind == kind)
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    rows = db.execute(stmt.order_by(Message.id.desc()).limit(limit + 1)).all()
    return [(a, m, name) for a, m, name in rows]


def count_attachments(db: Session, room: ChatRoom) -> dict[str, int]:
    """이 방의 첨부 개수를 종류(image/file)별로."""
    rows = db.execute(
        select(MessageAttachment.kind, func.count(MessageAttachment.id))
        .join(Message, Message.id == MessageAttachment.message_id)
        .where(room_messages(room))
        .group_by(MessageAttachment.kind)
    ).all()
    return {kind: count for kind, count in rows}
