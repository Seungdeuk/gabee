"""주간 가족 뉴스 읽기. 저장본을 상태로 바꿔 돌려줄 뿐 만들지 않는다(LLM 호출·생성은 T26-b)."""

from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.shared import member_exit
from app.shared.schema import monitor

from . import repository
from .models import MemberWeeklyNews
from .schemas import NewsItemOut, NewsOut, NewsSourceOut
from .week import ready_to_generate, validate_week, week_end_of, week_start_of

# 만드는 중으로 이만큼 지나면 서버가 죽은 것으로 보고 다시 만들 수 있다(읽기도 그 줄을 만드는 중으로 보여 주지 않는다)
PENDING_STALE = timedelta(minutes=5)

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


def delete_my_news_on_leave(db: Session, group_id: str, user_id: str) -> list[Path]:
    """가족을 나가는 사람의 그 가족 뉴스를 지운다(같은 트랜잭션: 실패하면 가족 나가기도 취소된다). 저장된 문장에는 되돌린 이름이
    들어 있어, 나간 뒤에도 남기면 개인정보 보관이 되고 같은 가족에 다시 들어왔을 때 옛 뉴스가 보인다(2026-11-11 결정).
    이 DB 에 뉴스 표가 아직 없으면(코드가 DB 보다 먼저 배포) 지울 줄도 없으니 건너뛴다. 디스크 파일은 없다."""
    if not monitor.status().feature_ready("weekly_news"):
        return []
    repository.delete_for_member(db, group_id, user_id)
    return []


member_exit.register(delete_my_news_on_leave)


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
    if row is not None and not (
        row.status == "pending" and repository.is_stale(row, now, PENDING_STALE)
    ):
        return _from_row(row, week_start)
    status = "not_generated" if ready_to_generate(week_start, now) else "too_early"
    return NewsOut(status=status, week_start=week_start, week_end=week_end_of(week_start))
