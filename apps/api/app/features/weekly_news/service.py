"""주간 가족 뉴스 읽기. 저장본을 상태로 바꿔 돌려줄 뿐 만들지 않는다(LLM 호출·생성은 T26-b)."""

from datetime import date, datetime

from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from . import repository
from .models import MemberWeeklyNews
from .schemas import NewsItemOut, NewsOut, NewsSourceOut
from .week import ready_to_generate, validate_week, week_end_of, week_start_of

# 저장 상태 → 응답 상태
_STATUS = {"ok": "ready", "pending": "pending", "failed": "failed", "empty": "empty"}


class _Body(BaseModel):
    """저장된 body JSON 의 모양. 저장 쪽(T26-b)이 이 모양만 쓰지만, 손으로 고치거나 옛 형식이어도 읽기가 죽지 않게 확인한다."""

    title: str | None = None
    items: list[NewsItemOut] = []


_SOURCES = TypeAdapter(list[NewsSourceOut])


def _from_row(row: MemberWeeklyNews, week_start: date) -> NewsOut:
    status = _STATUS.get(row.status, "failed")
    week_end = week_end_of(week_start)
    if status != "ready":
        return NewsOut(status=status, week_start=week_start, week_end=week_end)
    try:
        body = _Body.model_validate(row.body if row.body is not None else {})
        sources = _SOURCES.validate_python(row.sources if row.sources is not None else [])
    except ValidationError:
        # 저장된 JSON 이 깨졌다: 500 대신 실패로 돌려준다(앱이 규칙 기반 리포트로 대신 보여 준다)
        return NewsOut(status="failed", week_start=week_start, week_end=week_end)
    return NewsOut(
        status="ready",
        week_start=week_start,
        week_end=week_end,
        title=body.title,
        items=body.items,
        sources=sources,
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
