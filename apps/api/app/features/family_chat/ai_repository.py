"""가족 채팅 대화 요약(AI)의 DB 접근. 요약은 저장하지 않으므로 읽기만 한다."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember, User

from .models import ASSISTANT_USER_ID, Message, MessageShare
from .repository import family_messages, share_table_exists, shares_for
from .share_text import card_text


@dataclass(frozen=True)
class AiMessage:
    """공유 카드 메시지를 AI 로 읽을 때 쓰는 읽기 전용 복사본. Message 와 같은 필드이고 text 만 카드 요약이다.
    ORM 객체의 text 를 바꾸면 세션이 더러워져 DB 의 고정 문구가 요약으로 저장될 수 있어서 복사본을 쓴다."""

    id: int
    group_id: str
    room_id: str | None
    user_id: str
    text: str
    created_at: datetime
    deleted_at: datetime | None
    reply_to_id: int | None


def recent_messages(
    db: Session,
    group_id: str,
    limit: int,
    after_id: int = 0,
    room_id: str | None = None,
    include_assistant: bool = False,
) -> list[tuple[Message | AiMessage, str]]:
    """(after_id 뒤) 최근 메시지 limit 개를 오래된 순으로. room_id 가 없으면 이 그룹 가족 전체방, 있으면 그 1:1 방의 메시지만이다.
    다른 그룹의 메시지는 쿼리에 나오지 않는다. 1:1 방을 읽을 수 있는지(참가자인지·상대가 가족인지)는 부르는 쪽이 먼저 확인한다.
    공유 카드 메시지는 고정 문구 대신 카드 내용 요약(`share_text.card_text`)을 글자로 가진 복사본(AiMessage)으로 돌려준다.
    요약도 부르는 쪽이 일반 메시지처럼 가명화한다. 카드 표가 이 DB 에 없으면 고정 문구 그대로다."""
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
            # 가비의 답은 가족 대화가 아니라서 분석에서 뺀다(@가비 맥락에는 이미 한 말을 알도록 넣는다)
            or_(Message.user_id != ASSISTANT_USER_ID, include_assistant),
        )
        .order_by(Message.id.desc())
        .limit(limit)
    ).all()
    rows = list(reversed(rows))
    # 카드 표가 아직 없는 DB(공용 DB 반영 전)에서는 조회하지 않는다(500 대신 고정 문구로 동작)
    shares = shares_for(db, [m.id for m, _ in rows]) if rows and share_table_exists(db) else {}
    return [(_with_card(m, shares.get(m.id)), name) for m, name in rows]


def _with_card(message: Message, share: MessageShare | None) -> Message | AiMessage:
    if share is None:
        return message
    return AiMessage(
        id=message.id,
        group_id=message.group_id,
        room_id=message.room_id,
        user_id=message.user_id,
        text=card_text(share.kind, share.payload),
        created_at=message.created_at,
        deleted_at=message.deleted_at,
        reply_to_id=message.reply_to_id,
    )


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
