"""서비스 관리자 쪽 알림 규칙: 답 안 한 문의, AI 사용 급증, 승인 대기 참가 요청.

기준은 이 파일의 상수다. 바꾸면 docs/requirements/admin-alerts.md 도 같이 고친다.
다른 기능의 표(문의·AI 사용 기록·참가 요청)는 이 기능의 repository 가 표 이름으로 읽는다(다른 기능의 파일을 가져오지 않는다).

세 규칙 모두 지문에 한국 시간 날짜를 넣어 하루에 한 번만 알린다. 문구에는 개수와 대기 시간만 쓰고
문의 제목·내용, 가족 이름, 신청자, 사용자는 쓰지 않는다.

- 답 안 한 문의: new·working 상태로 등록한 지 6시간이 넘은 문의가 있으면 주의
- AI 사용 급증: 오늘 요청이 50건 이상이고 최근 7일 하루 평균의 3배 이상이면 주의
- 승인 대기 참가 요청: pending 상태로 24시간이 넘은 요청이 있으면 주의
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.shared.alert_rules import Finding, register
from app.shared.config import settings

from . import repository

STALE_SUPPORT_RULE = "stale_support"
STALE_SUPPORT_HOURS = 6
SUPPORT_MENU = "문의 및 신고"

AI_SPIKE_RULE = "ai_usage_spike"
AI_SPIKE_RATIO = 3
AI_SPIKE_MIN_REQUESTS = 50
AI_BASELINE_DAYS = 7
AI_MENU = "기능·AI › AI"

STALE_JOIN_RULE = "stale_join"
STALE_JOIN_HOURS = 24
JOIN_MENU = "사용자 › 가족"


def _aware(value: datetime) -> datetime:
    """시험 DB(SQLite)는 시간대 표기를 떼고 돌려준다. 저장된 시각은 항상 UTC 라서 표기가 없으면 UTC 로 본다."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _waited_hours(now: datetime, since: datetime) -> int:
    return max(0, int((now - _aware(since)).total_seconds() // 3600))


def _local_now(now: datetime) -> datetime:
    """한국 시간(설정 ai_day_utc_offset_hours)으로 민 시각. 날짜 경계를 세는 데만 쓴다."""
    return now + timedelta(hours=settings.ai_day_utc_offset_hours)


def _day_key(now: datetime) -> str:
    return _local_now(now).date().isoformat()


def _local_day_start(now: datetime) -> datetime:
    """오늘 한국 시간 자정이 UTC 로 언제인지."""
    local = _local_now(now)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(hours=settings.ai_day_utc_offset_hours)


def stale_support(db: Session, now: datetime) -> list[Finding]:
    count, oldest = repository.stale_support_tickets(db, now - timedelta(hours=STALE_SUPPORT_HOURS))
    if not count or oldest is None:
        return []
    message = (
        f"{STALE_SUPPORT_HOURS}시간 넘게 답이 없는 문의 {count}건 "
        f"(가장 오래된 것 {_waited_hours(now, oldest)}시간째)"
    )
    return [
        Finding(
            key=f"{STALE_SUPPORT_RULE}:{_day_key(now)}",
            rule=STALE_SUPPORT_RULE,
            severity="주의",
            message=message,
            menu=SUPPORT_MENU,
        )
    ]


def ai_usage_spike(db: Session, now: datetime) -> list[Finding]:
    start = _local_day_start(now)
    today = repository.count_ai_requests(db, start)
    if today < AI_SPIKE_MIN_REQUESTS:  # 적은 숫자의 흔들림 방지
        return []
    baseline = repository.count_ai_requests(db, start - timedelta(days=AI_BASELINE_DAYS), start)
    average = baseline / AI_BASELINE_DAYS
    if today < average * AI_SPIKE_RATIO:
        return []
    if average > 0:
        message = (
            f"오늘 AI 요청 {today}건, 최근 {AI_BASELINE_DAYS}일 하루 평균 {average:.0f}건의 "
            f"{today / average:.1f}배"
        )
    else:  # 예전 기록이 없을 때: 배수를 셀 수 없다
        message = f"오늘 AI 요청 {today}건, 최근 {AI_BASELINE_DAYS}일 하루 평균 0건"
    return [
        Finding(
            key=f"{AI_SPIKE_RULE}:{_day_key(now)}",
            rule=AI_SPIKE_RULE,
            severity="주의",
            message=message,
            menu=AI_MENU,
        )
    ]


def stale_join(db: Session, now: datetime) -> list[Finding]:
    count, oldest = repository.stale_join_requests(db, now - timedelta(hours=STALE_JOIN_HOURS))
    if not count or oldest is None:
        return []
    message = (
        f"{STALE_JOIN_HOURS}시간 넘게 승인 대기 중인 가족 참가 요청 {count}건 "
        f"(가장 오래된 것 {_waited_hours(now, oldest)}시간째)"
    )
    return [
        Finding(
            key=f"{STALE_JOIN_RULE}:{_day_key(now)}",
            rule=STALE_JOIN_RULE,
            severity="주의",
            message=message,
            menu=JOIN_MENU,
        )
    ]


register(STALE_SUPPORT_RULE, stale_support)
register(AI_SPIKE_RULE, ai_usage_spike)
register(STALE_JOIN_RULE, stale_join)
