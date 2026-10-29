"""게시판 목록 엔드포인트. family_chat 라우터에 포함되어 /family-chat/board 아래로 열린다. AI 를 부르지 않는다."""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import board_service
from .board_schemas import BoardOut

router = APIRouter(prefix="/board")

ROOM_ID = Query(None, max_length=32, description="대화방 id. 없으면 가족 전체방")


@router.get("", response_model=BoardOut)
def list_board(
    room_id: str | None = ROOM_ID,
    limit: int = Query(20, ge=1, le=50),
    before: str | None = Query(
        None, max_length=200, description="앞 응답의 next_before(이전 글을 이어서 볼 때)"
    ),
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> BoardOut:
    """공지로 올린 메시지의 기록(지난 공지 포함)을 올린 시각 최신순으로. 전체 본문·올린 사람·지금 공지인지·원본 삭제 여부가 함께 온다."""
    return board_service.list_board(db, user, group_id, room_id, limit, before)


@router.delete("/{post_id}", status_code=204)
def delete_board_post(
    post_id: str,
    room_id: str | None = ROOM_ID,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Response:
    """게시판 글을 지운다(방 안의 누구나). 지금 공지로 올라 있으면 고정 바에서도 내려간다. 원본 메시지는 그대로 남는다."""
    board_service.delete_post(db, user, group_id, post_id, room_id)
    return Response(status_code=204)
