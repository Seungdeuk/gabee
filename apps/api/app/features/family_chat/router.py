from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import service
from .ai_router import router as ai_router
from .schemas import (
    DirectRoomCreate,
    MessageCreate,
    MessageOut,
    ReadMark,
    ReadPosition,
    ReadStateOut,
    RoomOut,
    UnreadOut,
)

router = APIRouter(prefix="/family-chat", tags=["family-chat"])
router.include_router(ai_router)  # AI 대화 분석·추천(사용할 때만 AI 호출, 가족 전체방만)

# room_id 를 생략하면 가족 전체방이다(방 구조가 생기기 전 앱과 같은 동작).
ROOM_ID = Query(None, max_length=32, description="대화방 id. 없으면 가족 전체방")


@router.get("/rooms", response_model=list[RoomOut])
def list_rooms(
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[RoomOut]:
    return service.list_rooms(db, user, group_id)


@router.post("/rooms/direct", response_model=RoomOut)
def open_direct_room(
    body: DirectRoomCreate,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> RoomOut:
    return service.open_direct_room(db, user, group_id, body.user_id)


@router.get("/messages", response_model=list[MessageOut])
def list_messages(
    after_id: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    latest: bool = Query(False),
    before_id: int | None = Query(None, ge=1),
    room_id: str | None = ROOM_ID,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[MessageOut]:
    return service.list_messages(db, user, group_id, after_id, limit, latest, before_id, room_id)


@router.post("/messages", response_model=MessageOut, status_code=201)
def post_message(
    body: MessageCreate,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MessageOut:
    return service.post(db, user, group_id, body.text, body.room_id)


@router.post("/read", response_model=ReadPosition)
def mark_read(
    body: ReadMark,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> ReadPosition:
    return service.mark_read(db, user, group_id, body.message_id, body.room_id)


@router.get("/read-states", response_model=list[ReadStateOut])
def read_states(
    room_id: str | None = ROOM_ID,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[ReadStateOut]:
    return service.read_states(db, user, group_id, room_id)


@router.get("/unread", response_model=UnreadOut)
def unread(
    room_id: str | None = ROOM_ID,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> UnreadOut:
    return service.unread(db, user, group_id, room_id)
