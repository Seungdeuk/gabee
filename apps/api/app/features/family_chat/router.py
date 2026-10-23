from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import service, summary_service
from .schemas import MessageCreate, MessageOut
from .summary_schemas import SummaryIn, SummaryOut

router = APIRouter(prefix="/family-chat", tags=["family-chat"])


@router.get("/messages", response_model=list[MessageOut])
def list_messages(
    after_id: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[MessageOut]:
    return service.list_messages(db, group_id, after_id, limit)


@router.post("/messages", response_model=MessageOut, status_code=201)
def post_message(
    body: MessageCreate,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MessageOut:
    return service.post(db, user, group_id, body.text)


@router.post("/summary", response_model=SummaryOut)
def summarize(
    body: SummaryIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> SummaryOut:
    """이 가족 그룹의 최근 대화를 AI 로 요약한다(눌렀을 때만 외부 AI 로 보내고, 요약·대화는 저장하지 않는다).
    대화가 너무 적으면 400 too_few_messages, AI 설정이 없으면 503 llm_unavailable, 호출 실패는 503 llm_failed, 너무 잦으면 429."""
    return summary_service.summarize(db, user, group_id, body)
