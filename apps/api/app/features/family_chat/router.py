from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import service
from .ai_router import router as ai_router
from .media_router import router as media_router
from .photo_router import router as photo_router
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
from .search_router import router as search_router
from .todo_router import router as todo_router

router = APIRouter(prefix="/family-chat", tags=["family-chat"])
router.include_router(photo_router)  # 사진 보내기·보기(AI 를 부르지 않는다)
router.include_router(media_router)  # 사진·파일·동영상 모음(읽기 전용)
router.include_router(todo_router)  # 공동 할 일(가족 전체 공유, AI 를 부르지 않는다)
router.include_router(search_router)  # 대화 검색(글자 일치, AI 를 부르지 않는다)
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
    limit: int | None = Query(None, ge=1, le=200, description="기본 100, around_id 일 때 50"),
    latest: bool = Query(False),
    before_id: int | None = Query(None, ge=1),
    around_id: int | None = Query(
        None, ge=1, description="가운데 1개 + 앞뒤 각 limit//2 개(검색 결과로 점프할 때)"
    ),
    room_id: str | None = ROOM_ID,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[MessageOut]:
    return service.list_messages(
        db, user, group_id, after_id, limit, latest, before_id, room_id, around_id
    )


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
