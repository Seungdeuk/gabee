"""운영 관리자 쪽 알림 규칙: 서버 오류율.

기준은 이 파일의 상수다. 바꾸면 docs/requirements/admin-alerts.md 도 같이 고친다.

서버 오류율 (ops_request_metrics 표: 구간별 요청 수, 5xx 수)
- 최근 60분 요청이 20건 미만이면 판단하지 않는다(적은 숫자의 흔들림 방지)
- 5xx 비율 5% 이상이면 긴급, 1% 이상이면 주의
- 지문은 시(時) 단위라서, 다음 시간이 되면 같은 규칙도 다시 알릴 수 있다
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.shared.alert_rules import Finding, register

from . import repository

RULE = "server_error_rate"
WINDOW = timedelta(minutes=60)
MIN_REQUESTS = 20
CRITICAL_RATE = 0.05  # 긴급
WARN_RATE = 0.01  # 주의
MENU = "서버 상태"


def server_error_rate(db: Session, now: datetime) -> list[Finding]:
    rows = repository.totals_by_bucket(db, now - WINDOW)
    total = sum(count for _, _, count, _, _ in rows)
    errors = sum(count for _, status_class, count, _, _ in rows if status_class == "5xx")
    if total < MIN_REQUESTS:
        return []
    rate = errors / total
    if rate >= CRITICAL_RATE:
        severity, threshold = "긴급", CRITICAL_RATE
    elif rate >= WARN_RATE:
        severity, threshold = "주의", WARN_RATE
    else:
        return []
    message = (
        f"최근 60분 서버 오류 {rate * 100:.1f}% "
        f"(요청 {total}건 중 5xx {errors}건, 기준 {threshold * 100:.0f}%)"
    )
    return [
        Finding(
            key=f"{RULE}:{now:%Y-%m-%dT%H}",
            rule=RULE,
            severity=severity,
            message=message,
            menu=MENU,
        )
    ]


register(RULE, server_error_rate)
