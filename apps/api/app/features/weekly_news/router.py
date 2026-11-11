from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import generate, service
from .schemas import NewsOut

router = APIRouter(prefix="/report", tags=["report"])


def current_time() -> datetime:
    """서버의 현재 시각. 시험에서 `app.dependency_overrides` 로 고정한다."""
    return datetime.now(UTC)


@router.get("/news", response_model=NewsOut)
def get_news(
    week_start: date | None = None,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    now: datetime = Depends(current_time),
    db: Session = Depends(get_db),
) -> NewsOut:
    """내 가족 뉴스(저장본). 본인 것만 돌려주고, 저장본이 없어도 만들지 않는다."""
    return service.get_news(db, group_id, user.id, week_start, now)


@router.post("/news", response_model=NewsOut)
def create_news(
    week_start: date | None = None,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    now: datetime = Depends(current_time),
    db: Session = Depends(get_db),
) -> NewsOut:
    """내 그 주 가족 뉴스를 만든다(이미 만들었으면 AI 를 부르지 않고 저장본). 만들지 못하면 status=failed 로 돌려준다."""
    return generate.generate_news(db, group_id, user.id, week_start, now)
