"""가족 채팅 대화 요약(AI)의 DB 접근. 요약은 저장하지 않으므로 읽기만 한다."""

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember, User

from .models import ASSISTANT_USER_ID, Message
from .repository import family_messages


def recent_messages(
    db: Session, group_id: str, limit: int, after_id: int = 0, room_id: str | None = None
) -> list[tuple[Message, str]]:
    """(after_id 뒤) 최근 메시지 limit 개를 오래된 순으로. room_id 가 없으면 이 그룹 가족 전체방, 있으면 그 1:1 방의 메시지만이다.
    다른 그룹의 메시지는 쿼리에 나오지 않는다. 1:1 방을 읽을 수 있는지(참가자인지·상대가 가족인지)는 부르는 쪽이 먼저 확인한다."""
    room_filter = (
        and_(Message.group_id == group_id, Message.room_id == room_id)
        if room_id
        else family_messages(group_id)
    )
    rows = db.execute(
        select(Message, User.name)
        .join(User, User.id == Message.user_id)
        .where(
            room_filter,
            Message.id > after_id,
            Message.text != "",  # 사진 메시지(글자 없음)는 제외
            Message.deleted_at.is_(None),  # 보낸 사람이 지운 메시지는 AI 로 보내지 않는다
            Message.user_id != ASSISTANT_USER_ID,  # 가비의 답은 가족 대화가 아니라서 분석에서 뺀다
        )
        .order_by(Message.id.desc())
        .limit(limit)
    ).all()
    return [(m, name) for m, name in reversed(rows)]


def member_names(db: Session, group_id: str) -> list[tuple[str, ...]]:
    """이 그룹 구성원의 이름 사전. 구성원마다 (실제 이름, 표시 이름) 묶음 하나이고(표시 이름이 없거나 같으면 이름만),
    첫 번째가 대표 이름이다. 가명화가 한 사람의 모든 표기를 같은 토큰으로 묶는다. 정렬해서 돌려줘 같은 구성이면 항상 같은 순서다."""
    rows = db.execute(
        select(User.name, GroupMember.display_name)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group_id)
    ).all()
    people: set[tuple[str, ...]] = set()
    for name, display in rows:
        real = " ".join((name or "").split())
        shown = " ".join((display or "").split())
        if real:
            people.add((real, shown) if shown and shown != real else (real,))
        elif shown:
            people.add((shown,))
    return sorted(people)
