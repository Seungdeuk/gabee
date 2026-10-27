from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user, ensure_group_member
from app.shared.db import get_db

from . import handler, suggest
from .schemas import (
    AgentRequest,
    AgentResponse,
    ConfirmRequest,
    SuggestionsOut,
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


@router.get("/suggestions", response_model=SuggestionsOut)
def list_suggestions(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> SuggestionsOut:
    """대기 중인 추천(없으면 오늘 3묶음 안에서 새로 만든다). AI 를 부를 때만 동의·한도를 본다."""
    ensure_group_member(db, user.id, group_id)
    items, exhausted = suggest.supply(db, user.id, group_id)
    return SuggestionsOut(
        suggestions=[handler.suggestion_out(s) for s in items], exhausted=exhausted
    )
