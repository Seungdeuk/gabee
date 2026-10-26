"""채팅방 사진·파일·동영상 모음. family_chat 라우터에 포함되어 /family-chat/media 로 열린다."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import media_service
from .media_schemas import MediaPage

router = APIRouter()


@router.get("/media", response_model=MediaPage)
def list_media(
    room_id: str | None = Query(None, max_length=32, description="대화방 id. 없으면 가족 전체방"),
    kind: Literal["image", "file", "video", "all"] = Query("all"),
    limit: int = Query(40, ge=1, le=100),
    before_id: int | None = Query(None, ge=1, description="이 메시지 id 보다 오래된 것(다음 쪽)"),
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MediaPage:
    """그 방에서 공유된 첨부를 최신순으로. 방에 들어갈 수 없으면 404. 지금은 사진(image)만 있다."""
    return media_service.list_media(db, user, group_id, room_id, kind, limit, before_id)
