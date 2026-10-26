"""대화 검색 엔드포인트. family_chat 라우터에 포함되어 /family-chat/search 로 열린다. AI·외부 호출이 없다."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import search_service
from .search_schemas import SearchOut

router = APIRouter()


@router.get("/search", response_model=SearchOut)
def search_messages(
    q: str = Query(
        ...,
        max_length=500,
        description="검색어(공백 정리 후 1~100자). 공백으로 나눈 모든 낱말이 들어 있는 메시지",
    ),
    room_id: str | None = Query(
        None, max_length=32, description="이 방만 검색. 없으면 접근 가능한 모든 방"
    ),
    limit: int = Query(20, ge=1, le=50),
    before_id: int | None = Query(None, ge=1, description="이 id 보다 오래된 결과(다음 쪽)"),
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> SearchOut:
    """가족 전체방과 내가 참여한 1:1 방에서 글자가 일치하는 텍스트 메시지를 최신순으로 찾는다(사진 메시지 제외)."""
    return search_service.search(db, user, group_id, q, room_id, limit, before_id)
