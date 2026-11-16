"""주간 가족 뉴스의 주 경계·허용 범위·생성 시점 규칙(순수 함수).

- 한 주는 서비스 기준 시간대(`settings.ai_day_utc_offset_hours`, 기본 +9 = KST)의 월요일부터 일요일이다.
  `schedule/timeutil.local_tz()`·`knowledge/service.created_bounds()` 와 같은 설정을 쓰지만,
  다른 기능의 내부 파일을 import 하지 않으려고 여기서 직접 계산한다.
- 모든 함수가 `now` 를 인자로 받아서 시험에서 시간을 고정할 수 있다. 시간대 없는 `datetime` 은 UTC 로 본다.
- 허용 범위는 기존 리포트(`docs/requirements/report.md`)와 같다: 이번 주부터 8주 전까지, 미래 주 없음.
"""

from datetime import UTC, date, datetime, time, timedelta, timezone

from app.shared.config import settings
from app.shared.errors import bad_request

# 이번 주 뉴스는 일요일 이 시각(서비스 시간대) 이후에만 만든다. 나중에 설정으로 바꿀 수 있게 모듈 상수로 둔다.
READY_HOUR = 18
# 이번 주 기준으로 몇 주 전까지 볼 수 있는가(report.md 의 "최근 8주").
MAX_WEEKS_BACK = 8


def _local_tz() -> timezone:
    return timezone(timedelta(hours=settings.ai_day_utc_offset_hours))


def _local(now: datetime) -> datetime:
    """`now` 를 서비스 시간대의 시각으로 바꾼다(시간대 없으면 UTC 로 간주)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(_local_tz())


def _is_plain_date(value: object) -> bool:
    """`date` 이지만 `datetime` 은 아닌 값만 주 시작일로 받는다(datetime 은 date 의 하위 클래스라 따로 거른다)."""
    return isinstance(value, date) and not isinstance(value, datetime)


def week_start_of(now: datetime) -> date:
    """`now` 가 속한 주의 월요일(서비스 시간대 날짜)."""
    today = _local(now).date()
    return today - timedelta(days=today.weekday())


def week_end_of(week_start: date) -> date:
    """그 주의 일요일."""
    return week_start + timedelta(days=6)


def validate_week(week_start: date, now: datetime) -> None:
    """월요일이 아니거나, 미래 주이거나, 이번 주 기준 8주 전보다 오래되면 400 `invalid_week`.

    오류 메시지에는 입력값을 담지 않는다.
    """
    this_week = week_start_of(now)
    oldest = this_week - timedelta(weeks=MAX_WEEKS_BACK)
    if (
        not _is_plain_date(week_start)
        or week_start.weekday() != 0
        or week_start > this_week
        or week_start < oldest
    ):
        raise bad_request("invalid_week", "볼 수 없는 주예요")


def ready_to_generate(week_start: date, now: datetime) -> bool:
    """그 주의 뉴스를 지금 만들어도 되는가.

    지난 주들은 항상 True, 미래 주(와 월요일이 아닌 날짜)는 False,
    이번 주는 그 주 일요일 `READY_HOUR` 시(서비스 시간대) 이후에만 True.
    """
    if not _is_plain_date(week_start) or week_start.weekday() != 0:
        return False
    local_now = _local(now)
    this_week = week_start_of(now)
    if week_start > this_week:
        return False
    if week_start < this_week:
        return True
    ready_at = datetime.combine(week_end_of(week_start), time(READY_HOUR), tzinfo=local_now.tzinfo)
    return local_now >= ready_at


def issue_of(week_start: date) -> tuple[int, int]:
    """신문 호수: (ISO 연도, ISO 주 번호). 서버가 정한 주(월요일)의 ISO 주차라서 연말·연초에는 달력 연도와 다를 수 있다
    (예: 2025-12-29 주는 2026 년 1호)."""
    iso = week_start.isocalendar()
    return iso.year, iso.week
