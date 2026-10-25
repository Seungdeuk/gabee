from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import service
from .ai_router import router as ai_router
from .schemas import (
    MessageCreate,
    MessageOut,
    ReadMark,
    ReadPosition,
    ReadStateOut,
    UnreadOut,
)

router = APIRouter(prefix="/family-chat", tags=["family-chat"])
router.include_router(ai_router)  # AI 대화 분석·추천(사용할 때만 AI 호출)


@router.get("/messages", response_model=list[MessageOut])
def list_messages(
    after_id: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    latest: bool = Query(False),
    before_id: int | None = Query(None, ge=1),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[MessageOut]:
    return service.list_messages(db, group_id, after_id, limit, latest, before_id)


@router.post("/messages", response_model=MessageOut, status_code=201)
def post_message(
    body: MessageCreate,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MessageOut:
    return service.post(db, user, group_id, body.text)


@router.post("/read", response_model=ReadPosition)
def mark_read(
    body: ReadMark,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> ReadPosition:
    return service.mark_read(db, user, group_id, body.message_id)


@router.get("/read-states", response_model=list[ReadStateOut])
def read_states(
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[ReadStateOut]:
    return service.read_states(db, group_id)


@router.get("/unread", response_model=UnreadOut)
def unread(
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> UnreadOut:
    return service.unread(db, user, group_id)
