from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user, ensure_group_member
from app.shared.db import get_db

from . import handler, suggest
from .schemas import (
    AgentRequest,
    AgentResponse,
    ConfirmRequest,
    SuggestionLater,
    SuggestionOut,
    SuggestionsOut,
    SuggestionsRequest,
)

# 메인 오케스트레이터가 생기기 전까지 일정 에이전트를 부르는 입구. 메인이 생기면 메인이 handler.handle 을 직접 부른다
router = APIRouter()


@router.post("/agent", response_model=AgentResponse)
def ask_agent(
    body: AgentRequest,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AgentResponse:
    return handler.handle(db, user.id, group_id, body)


@router.post("/agent/confirm", response_model=AgentResponse)
def confirm_agent_action(
    body: ConfirmRequest,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AgentResponse:
    """확인 카드(공유해서 등록 등)의 버튼. AI 를 부르지 않고 한도도 쓰지 않는다."""
    return handler.confirm(db, user.id, group_id, body)


def _slot_out(slot: suggest.Slot) -> SuggestionsOut:
    return SuggestionsOut(
        suggestions=[handler.suggestion_out(s) for s in slot.items],
        exhausted=slot.state == suggest.STATE_EXHAUSTED,
        state=slot.state,
        can_refresh=slot.can_refresh,
    )


@router.get("/suggestions", response_model=SuggestionsOut)
def list_suggestions(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> SuggestionsOut:
    """오늘의 추천 슬롯(대기 추천이 있으면 그대로, 없으면 오늘 호출이 남았을 때 새로 만든다). AI 를 부를 때만 동의·한도를 본다.
    개인 AI 채팅은 보내지 않으므로 이 입구로 만든 추천에는 쓰이지 않는다(앱은 POST 를 쓴다)."""
    ensure_group_member(db, user.id, group_id)
    return _slot_out(suggest.supply_slot(db, user.id, group_id))


@router.post("/suggestions", response_model=SuggestionsOut)
def create_suggestions(
    body: SuggestionsRequest | None = None,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> SuggestionsOut:
    """GET 과 같은 결과인데 개인 AI 채팅의 최근 내 말(`chat`)을 추천의 입력으로 함께 받는다. 대기 추천이 있으면 AI 를 부르지 않는다."""
    ensure_group_member(db, user.id, group_id)
    return _slot_out(suggest.supply_slot(db, user.id, group_id, body.chat if body else None))


@router.put("/suggestions/{suggestion_id}/later", response_model=SuggestionOut)
def mark_suggestion_later(
    suggestion_id: str,
    body: SuggestionLater,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> SuggestionOut:
    """추천의 "나중에" 표시를 켜거나 끈다(켜면 나중에, 끄면 다시 대기). 확정된 추천이나 남의 추천은 400. AI 를 부르지 않는다."""
    ensure_group_member(db, user.id, group_id)
    return handler.suggestion_out(
        suggest.set_later(db, user.id, group_id, suggestion_id, body.later)
    )
