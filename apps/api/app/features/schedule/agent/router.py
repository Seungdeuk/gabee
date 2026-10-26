from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import handler
from .schemas import AgentRequest, AgentResponse, ConfirmRequest

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
