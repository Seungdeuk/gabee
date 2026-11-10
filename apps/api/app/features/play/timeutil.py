from datetime import UTC, datetime, timedelta, timezone

from app.shared.config import settings


def local_tz() -> timezone:
    """서비스 기준 시간대(기본 한국 시간). "하루"와 "이번 주 월요일"은 이 시간대로 센다."""
    return timezone(timedelta(hours=settings.ai_day_utc_offset_hours))


def aware(dt: datetime) -> datetime:
    """SQLite 는 시간대 없는 값으로 돌려주므로 UTC 로 보고 시간대를 붙인다(PostgreSQL 은 이미 붙어 있다)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def local_day_start(dt: datetime) -> datetime:
    """dt 가 속한 한국 시간 하루의 시작(0시)을 UTC 로 돌려준다."""
    local = aware(dt).astimezone(local_tz())
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def week_start(now: datetime) -> datetime:
    """이번 주 월요일 0시(한국 시간)를 UTC 로."""
    day = local_day_start(now)
    local = day.astimezone(local_tz())
    return (local - timedelta(days=local.weekday())).astimezone(UTC)


def month_start(now: datetime) -> datetime:
    local = aware(now).astimezone(local_tz())
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
