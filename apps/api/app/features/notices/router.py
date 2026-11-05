"""앱의 공지사항 보기. 로그인한 사용자 누구나 같은 목록을 받는다(가족이 없어도 된다)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_user
from app.shared.db import get_db

from . import service
from .schemas import NoticeList

router = APIRouter(prefix="/notices", tags=["notices"])


@router.get("", response_model=NoticeList)
def list_notices(_: User = Depends(current_user), db: Session = Depends(get_db)) -> NoticeList:
    """서비스 공지 최근순 최대 100건. 쓰기는 서비스 관리자 API(/admin/service/notices)만 한다."""
    return service.latest(db)
