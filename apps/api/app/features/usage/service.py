"""체류시간 저장 규칙: 최근 7일 안의 날짜만 받고, 탭별 초와 앱 전체 합계(app 줄)를 그날 줄에 더한다."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.config import settings
from app.shared.errors import ApiError

from . import repository
from .models import APP_TAB
from .schemas import UsageReportIn

KEEP_DAYS = 7  # 이보다 오래된 날짜의 기록은 받지 않는다(기기 시계가 크게 틀린 경우 등)


def today(now: datetime) -> date:
    """한국 시간(설정 ai_day_utc_offset_hours, 기본 +9) 기준 오늘."""
    return (now + timedelta(hours=settings.ai_day_utc_offset_hours)).date()


def report(db: Session, user: User, body: UsageReportIn, now: datetime | None = None) -> None:
    """앱이 보낸 사용 기록 한 번을 저장한다. 날짜가 범위 밖이면 422."""
    now = now or datetime.now(UTC)
    base = today(now)
    if not (base - timedelta(days=KEEP_DAYS) <= body.day <= base + timedelta(days=1)):
        raise ApiError(422, "usage_day_out_of_range", "사용 날짜가 범위를 벗어났어요")
    tabs = body.clean_tabs()
    total = sum(tabs.values())
    if total == 0 and body.opens == 0:
        return
    rows = [(tab, sec, 0) for tab, sec in tabs.items()]
    rows.append((APP_TAB, total, body.opens))  # 앱 전체 합계와 실행 횟수
    repository.add_usage(db, user.id, body.day, rows, now)
