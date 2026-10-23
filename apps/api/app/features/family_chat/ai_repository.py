"""가족 채팅 대화 요약(AI)의 DB 접근. 요약은 저장하지 않으므로 읽기만 한다."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.family_group.models import User

from .models import Message


def recent_messages(
    db: Session, group_id: str, limit: int, after_id: int = 0
) -> list[tuple[Message, str]]:
    """이 그룹의 (after_id 뒤) 최근 메시지 limit 개를 오래된 순으로. 다른 그룹의 메시지는 쿼리에 나오지 않는다."""
    rows = db.execute(
        select(Message, User.name)
        .join(User, User.id == Message.user_id)
        .where(Message.group_id == group_id, Message.id > after_id)
        .order_by(Message.id.desc())
        .limit(limit)
    ).all()
    return [(m, name) for m, name in reversed(rows)]
