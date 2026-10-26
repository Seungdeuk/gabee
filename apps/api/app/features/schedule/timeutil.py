from datetime import timedelta, timezone

from app.shared.config import settings


def local_tz() -> timezone:
    """서비스 기준 시간대(기본 한국 시간). 날짜·시간을 시각 하나로 합치거나 나눌 때 쓴다."""
    return timezone(timedelta(hours=settings.ai_day_utc_offset_hours))
