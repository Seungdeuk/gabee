"""주간 가족 뉴스 읽기. 저장본을 상태로 바꿔 돌려줄 뿐 만들지 않는다(LLM 호출·생성은 T26-b)."""

from datetime import date, datetime

from sqlalchemy.orm import Session

from . import repository
from .models import MemberWeeklyNews
from .schemas import NewsOut
from .week import ready_to_generate, validate_week, week_end_of, week_start_of

# 저장 상태 → 응답 상태
_STATUS = {"ok": "ready", "pending": "pending", "failed": "failed", "empty": "empty"}


def _from_row(row: MemberWeeklyNews, week_start: date) -> NewsOut:
    status = _STATUS.get(row.status, "failed")
    week_end = week_end_of(week_start)
    if status != "ready":
        return NewsOut(status=status, week_start=week_start, week_end=week_end)
    body = row.body or {}
    return NewsOut(
        status="ready",
        week_start=week_start,
        week_end=week_end,
        title=body.get("title"),
        items=body.get("items") or [],
        sources=row.sources or [],
        generated_at=row.updated_at,
        ai_generated=True,
        model=row.model,
    )


def get_news(
    db: Session, group_id: str, user_id: str, week_start: date | None, now: datetime
) -> NewsOut:
    """요청한 구성원 본인의 그 주 뉴스. `week_start` 가 None 이면 이번 주.

    저장본이 없으면 이번 주이고 아직 만들 때가 아니면 `too_early`, 그 밖은 `not_generated`.

    Raises:
        ApiError: 월요일이 아니거나 허용 범위 밖의 주(400 `invalid_week`).
    """
    if week_start is None:
        week_start = week_start_of(now)
    validate_week(week_start, now)
    row = repository.get_for_member(db, group_id, user_id, week_start)
    if row is not None:
        return _from_row(row, week_start)
    status = "not_generated" if ready_to_generate(week_start, now) else "too_early"
    return NewsOut(status=status, week_start=week_start, week_end=week_end_of(week_start))
