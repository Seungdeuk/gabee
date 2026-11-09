"""가비의 기억: 사용자가 기억해 달라고 한 짧은 사실을 저장해 다음 대화에서 쓴다(docs/requirements/ai_assistant-memory.md).

대화 전체는 저장하지 않는다. 본인 것만 읽고 지울 수 있고, 메인 채팅의 AI 채팅 탭에서만 쓴다."""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.shared.errors import not_found
from app.shared.high_risk_guard import has_high_risk

from .models import AssistantMemory

MAX_MEMORIES = 50
MAX_TEXT = 200


def _normal(text: str) -> str:
    return " ".join(text.split())


def list_for(db: Session, group_id: str, user_id: str) -> list[AssistantMemory]:
    return list(
        db.scalars(
            select(AssistantMemory)
            .where(AssistantMemory.group_id == group_id, AssistantMemory.user_id == user_id)
            .order_by(AssistantMemory.created_at.desc(), AssistantMemory.id)
        )
    )


def _checked(text: str) -> str:
    """공백을 정리한 글. 빈 글, 긴 글, 고위험 번호는 ValueError."""
    clean = _normal(text)
    if not clean:
        raise ValueError("기억할 내용이 비어 있어요")
    if len(clean) > MAX_TEXT:
        raise ValueError(f"{MAX_TEXT}자 안으로 줄여서 저장해 주세요")
    if has_high_risk(clean):
        raise ValueError("주민번호·카드·계좌·비밀번호는 기억해 둘 수 없어요")
    return clean


def _mine(db: Session, group_id: str, user_id: str, memory_id: str) -> AssistantMemory:
    """내 기억 한 줄. 없거나 남의 것이면 같은 404 로 답한다."""
    row = db.scalar(
        select(AssistantMemory).where(
            AssistantMemory.id == memory_id,
            AssistantMemory.group_id == group_id,
            AssistantMemory.user_id == user_id,
        )
    )
    if row is None:
        raise not_found("기억")
    return row


def remember(db: Session, group_id: str, user_id: str, text: str) -> dict:
    """사실 하나를 저장한다. 고위험 번호, 빈 글, 긴 글, 개수 초과는 ValueError 로 모델에 돌려줘 사용자에게 설명하게 한다."""
    clean = _checked(text)
    rows = list_for(db, group_id, user_id)
    if any(_normal(r.text).casefold() == clean.casefold() for r in rows):
        return {"done": True, "already": True, "text": clean}
    if len(rows) >= MAX_MEMORIES:
        raise ValueError(
            f"기억은 {MAX_MEMORIES}개까지예요. 마이 탭의 가비의 기억에서 정리해 주세요"
        )
    row = AssistantMemory(id=uuid.uuid4().hex[:12], group_id=group_id, user_id=user_id, text=clean)
    db.add(row)
    db.commit()
    return {"done": True, "id": row.id, "text": clean}


def update(db: Session, group_id: str, user_id: str, memory_id: str, text: str) -> AssistantMemory:
    """내 기억의 내용을 고친다. 다른 기억과 같아지면 ValueError."""
    row = _mine(db, group_id, user_id, memory_id)
    clean = _checked(text)
    if any(
        r.id != row.id and _normal(r.text).casefold() == clean.casefold()
        for r in list_for(db, group_id, user_id)
    ):
        raise ValueError("이미 같은 내용을 기억하고 있어요")
    row.text = clean
    db.commit()
    return row


def forget(db: Session, group_id: str, user_id: str, memory_id: str) -> dict:
    """내 기억 하나를 지운다."""
    db.delete(_mine(db, group_id, user_id, memory_id))
    db.commit()
    return {"done": True}


def forget_all(db: Session, group_id: str, user_id: str) -> int:
    """내 기억을 모두 지우고 지운 개수를 돌려준다."""
    gone = db.scalar(
        select(func.count())
        .select_from(AssistantMemory)
        .where(AssistantMemory.group_id == group_id, AssistantMemory.user_id == user_id)
    )
    db.execute(
        delete(AssistantMemory).where(
            AssistantMemory.group_id == group_id, AssistantMemory.user_id == user_id
        )
    )
    db.commit()
    return int(gone or 0)


def note_lines(rows: list[AssistantMemory]) -> str:
    """시스템 안내에 붙일 줄: id | 내용."""
    return "\n".join(f"- {r.id} | {r.text}" for r in rows)
