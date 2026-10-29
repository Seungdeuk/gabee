"""대화 검색의 DB 접근. 방 권한은 SQL 조건으로 건다(가져온 뒤에 숨기지 않는다)."""

from collections.abc import Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.features.family_group.models import User

from .models import FAMILY, ChatRoom, ChatRoomMember, Message
from .repository import get_family_room, my_direct_rooms

ESCAPE = "\\"


def accessible_rooms(db: Session, group_id: str, user_id: str) -> list[ChatRoom]:
    """내가 검색할 수 있는 방: 가족 전체방(맨 앞) + 내가 참여한 1:1 방."""
    return [get_family_room(db, group_id), *my_direct_rooms(db, group_id, user_id)]


def message_scope(group_id: str, rooms: Sequence[ChatRoom]):
    """이 방들의 메시지 조건. 가족 전체방이 있으면 room_id 가 비어 있는 옛 메시지도 포함한다."""
    parts = [Message.room_id.in_([r.id for r in rooms])]
    if any(r.kind == FAMILY for r in rooms):
        parts.append(Message.room_id.is_(None))
    return and_(Message.group_id == group_id, or_(*parts))


def like_pattern(word: str) -> str:
    """낱말을 '포함' 검색용 LIKE 패턴으로. %, _, \\ 는 글자 그대로 찾도록 이스케이프한다."""
    escaped = word.replace(ESCAPE, ESCAPE * 2).replace("%", ESCAPE + "%").replace("_", ESCAPE + "_")
    return f"%{escaped}%"


def search(
    db: Session,
    group_id: str,
    rooms: Sequence[ChatRoom],
    words: Sequence[str],
    limit: int,
    before_id: int | None,
) -> list[tuple[Message, str]]:
    """모든 낱말이 글자로 들어 있는 텍스트 메시지를 최신순으로 limit 개(호출하는 쪽이 한 개 더 요청해 다음 쪽을 안다).
    대소문자는 구분하지 않는다(PostgreSQL ILIKE, SQLite LIKE)."""
    stmt = (
        select(Message, User.name)
        .join(User, User.id == Message.user_id)
        .where(message_scope(group_id, rooms), Message.text != "", Message.deleted_at.is_(None))
    )
    for word in words:
        stmt = stmt.where(Message.text.ilike(like_pattern(word), escape=ESCAPE))
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    rows = db.execute(stmt.order_by(Message.id.desc()).limit(limit))
    return [(m, name) for m, name in rows]


def peers(db: Session, room_ids: Sequence[str], user_id: str) -> dict[str, str]:
    """1:1 방들의 상대 user_id."""
    if not room_ids:
        return {}
    return dict(
        db.execute(
            select(ChatRoomMember.room_id, ChatRoomMember.user_id).where(
                ChatRoomMember.room_id.in_(list(room_ids)), ChatRoomMember.user_id != user_id
            )
        ).all()
    )
