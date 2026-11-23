"""운영 관리자 쪽 알림 규칙: 서버 오류율, 처음 보는 서버 오류.

기준은 이 파일의 상수다. 바꾸면 docs/requirements/admin-alerts.md 도 같이 고친다.

서버 오류율 (ops_request_metrics 표: 구간별 요청 수, 5xx 수)
- 최근 60분 요청이 20건 미만이면 판단하지 않는다(적은 숫자의 흔들림 방지)
- 5xx 비율 5% 이상이면 긴급, 1% 이상이면 주의
- 지문은 시(時) 단위라서, 다음 시간이 되면 같은 규칙도 다시 알릴 수 있다

처음 보는 서버 오류 (ops_error_events 표)
- 최근 24시간에 처음 나온 (오류 종류, 경로) 조합이 있으면 주의. 그 전에 같은 조합이 한 번이라도 있었으면 새것이 아니다
- 서버 오류(5xx·처리되지 않은 예외)만 본다. 401/403 같은 인증 실패는 보지 않는다
- 한 번 점검에 최대 10개(횟수가 많은 것 먼저). 한 조합은 한 번만 알린다(지문에 시간이 없다)
- 문구에는 오류 종류·경로·횟수만 쓴다. 오류 메시지 본문과 trace id 는 쓰지 않는다
"""

import hashlib
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


NEW_ERROR_RULE = "new_error"
NEW_ERROR_WINDOW = timedelta(hours=24)
NEW_ERROR_LIMIT = 10  # 한 번 점검에 알리는 최대 개수(배포가 크게 깨졌을 때 알림이 쏟아지지 않게)


def new_server_error(db: Session, now: datetime) -> list[Finding]:
    pairs = repository.new_server_error_pairs(db, now - NEW_ERROR_WINDOW, NEW_ERROR_LIMIT)
    findings = []
    for event_type, route, occurrences, _first_seen in pairs:
        # 종류·경로가 길어도 기록표의 key(120자)에 들어가도록 짧은 해시로 지문을 만든다
        digest = hashlib.sha256(f"{event_type}|{route}".encode()).hexdigest()[:16]
        message = f"처음 보는 서버 오류 {event_type} · {route} ({occurrences}회)"
        findings.append(
            Finding(
                key=f"{NEW_ERROR_RULE}:{digest}",
                rule=NEW_ERROR_RULE,
                severity="주의",
                message=message[:200],  # 기록표 message 칸(200자)을 넘지 않게
                menu=MENU,
            )
        )
    return findings


register(NEW_ERROR_RULE, new_server_error)
