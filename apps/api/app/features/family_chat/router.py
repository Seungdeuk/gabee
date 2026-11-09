from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import delete_service, reaction_service, service
from .ai_router import router as ai_router
from .board_router import router as board_router
from .file_router import router as file_router
from .link_router import router as link_router
from .media_router import router as media_router
from .photo_router import router as photo_router
from .pin_router import router as pin_router
from .schemas import (
    DeletedOut,
    DirectRoomCreate,
    MessageCreate,
    MessageOut,
    MuteOut,
    MuteSet,
    ReactionIn,
    ReadMark,
    ReadPosition,
    ReadStateOut,
    RoomOut,
    UnreadOut,
)
from .search_router import router as search_router
from .todo_router import router as todo_router

router = APIRouter(prefix="/family-chat", tags=["family-chat"])
router.include_router(file_router)  # 문서 파일 보내기·받기(AI 를 부르지 않는다)
router.include_router(photo_router)  # 사진 보내기·보기(AI 를 부르지 않는다)
router.include_router(media_router)  # 사진·파일·동영상 모음(읽기 전용)
router.include_router(todo_router)  # 공동 할 일(가족 전체 공유, AI 를 부르지 않는다)
router.include_router(search_router)  # 대화 검색(글자 일치, AI 를 부르지 않는다)
router.include_router(
    board_router
)  # 게시판 목록(지난 공지 포함, 방 안의 누구나 삭제, AI 를 부르지 않는다)
router.include_router(pin_router)  # 고정 메시지(공지, 방 안의 누구나, AI 를 부르지 않는다)
router.include_router(
    link_router
)  # 메시지-일정·할 일 연결(등록됨 표시·원본 이동, AI 를 부르지 않는다)
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


@router.put("/rooms/{room_id}/mute", response_model=MuteOut)
def set_room_mute(
    room_id: str,
    body: MuteSet,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MuteOut:
    """이 방의 알림을 나만 끄거나 켠다(멱등). 설정만 저장한다."""
    return service.set_room_muted(db, user, group_id, room_id, body.muted)


@router.post("/rooms/{room_id}/leave", status_code=204)
def leave_room(
    room_id: str,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Response:
    """1:1 방을 나간다(204). 내 목록에서만 사라지고 상대는 기록을 그대로 갖는다(상대 방은 읽기 전용, 새 메시지는 409 peer_left_room).
    둘 다 나가면 대화·사진·문서 파일이 모두 지워진다(되돌릴 수 없다). 가족 전체방은 400 cannot_leave_family_room, 내 방이 아니거나 이미 나갔으면 404."""
    service.leave_room(db, user, group_id, room_id)
    return Response(status_code=204)


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
    return service.post(db, user, group_id, body.text, body.room_id, body.reply_to_id)


@router.get("/messages/deleted", response_model=DeletedOut)
def deleted_messages(
    since: datetime = Query(
        ..., description="이 시각 이후에 지워진 메시지(서버 시각, 앞선 응답의 server_time)"
    ),
    room_id: str | None = ROOM_ID,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> DeletedOut:
    """이미 받아 둔 메시지 중 그 뒤에 지워진 것을 알려 준다(새 메시지만 조회하는 앱이 삭제를 따라가게)."""
    return delete_service.deleted_since(db, user, group_id, since, room_id)


@router.put("/messages/{message_id}/reaction", response_model=MessageOut)
def react_to_message(
    message_id: int,
    body: ReactionIn,
    room_id: str | None = ROOM_ID,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MessageOut:
    """내 반응을 정한다(한 메시지에 하나, 다른 이모지를 보내면 바뀐다). 허용 이모지 6개만, 지운 메시지에는 못 한다."""
    return reaction_service.react(db, user, group_id, message_id, body.emoji, room_id)


@router.delete("/messages/{message_id}/reaction", response_model=MessageOut)
def remove_reaction(
    message_id: int,
    room_id: str | None = ROOM_ID,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MessageOut:
    """내 반응을 지운다(없어도 같은 결과)."""
    return reaction_service.unreact(db, user, group_id, message_id, room_id)


@router.delete("/messages/{message_id}", response_model=MessageOut)
def delete_message(
    message_id: int,
    room_id: str | None = ROOM_ID,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MessageOut:
    """내가 보낸 메시지를 지운다(본문·사진도 서버에서 비운다). 이미 지웠으면 그대로 돌려준다."""
    return delete_service.delete_message(db, user, group_id, message_id, room_id)


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
