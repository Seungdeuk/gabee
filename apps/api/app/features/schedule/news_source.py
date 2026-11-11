"""주간 가족 뉴스의 일정 재료를 읽는다(`shared/weekly_sources.py` 에 등록, router 가 import 하면 등록된다).

내 줄(주인이 나인 일정 + 주인이 없던 옛 줄, 지운 줄 제외)의 **공유 약속**과 **완료한 공유 할 일**만 낸다. "공유"는 컬럼이 아니라
`service.with_sharing` 이 계산하는 값이라 그 계산을 거쳐 거른다(보낸 사람의 원본과 받은 사람의 복사본 모두 공유다). 대기 중(`pending`)
일정도 포함한다(규칙 기반 리포트와 숫자를 맞추려는 결정). 낸 값은 제목·날짜·시작 시각뿐이고 메모·장소·함께하는 사람은 내지 않는다."""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.shared import weekly_sources
from app.shared.weekly_sources import SourceRecord

from . import repository as repo
from . import service
from .constants import KIND_TODO
from .models import Event
from .timeutil import local_tz


def _day_of(event: Event) -> date | None:
    """그 줄의 날짜. start_date 가 없는 옛 줄은 starts_at 의 서비스 시간대 날짜."""
    if event.start_date is not None:
        return event.start_date
    if event.starts_at is None:
        return None
    # SQLite 는 시간대를 지우고 돌려주므로 UTC 로 본다(PostgreSQL 은 aware). 안 그러면 서버 PC 의 시간대로 읽힌다
    starts = event.starts_at if event.starts_at.tzinfo else event.starts_at.replace(tzinfo=UTC)
    return starts.astimezone(local_tz()).date()


def week_events(
    db: Session, group_id: str, user_id: str, start: date, end: date
) -> list[SourceRecord]:
    """그 구성원의 그 주 공유 약속·완료한 공유 할 일(제목·날짜·시작 시각만)."""
    tz = local_tz()
    utc_start = datetime.combine(start, time.min, tzinfo=tz).astimezone(UTC)
    utc_end = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    events = repo.list_week(db, group_id, user_id, start, end, utc_start, utc_end)
    records: list[SourceRecord] = []
    for event in service.with_sharing(db, user_id, events):
        day = _day_of(event)
        if not event.shared or day is None:
            continue
        records.append(
            SourceRecord(
                kind="todo" if event.kind == KIND_TODO else "event",
                ref=event.id,
                title=event.title,
                day=day,
                start_time=event.start_time.strftime("%H:%M") if event.start_time else None,
            )
        )
    return records


weekly_sources.register_provider(weekly_sources.SCHEDULE, "schedule", week_events)
