"""운영 숫자(서버 요청·오류)를 관리자 챗봇 명단(shared/admin_facts)에 올린다.

오류는 종류·경로·상태·횟수만 담는다. 오류 message 와 trace id 는 쓰지 않는다.
수집이 꺼져 있으면 0 이 진짜 0 이 아니므로 '알 수 없음'으로 보낸다.
"""

from sqlalchemy.orm import Session

from app.shared.admin_facts import register

from . import query_service

RANGE = "24h"
RECENT_ERRORS = 5


def requests(db: Session) -> list[str]:
    o = query_service.summary(db, RANGE)
    if not o.metrics_enabled:
        return ["서버 요청 지표: 수집이 꺼져 있어 알 수 없음"]
    return [
        f"최근 24시간 요청: {o.requests}건",
        f"최근 24시간 5xx 오류: {o.errors_5xx}건, 4xx: {o.errors_4xx}건, 오류율 {o.error_rate:.2%}",
        f"최근 24시간 평균 응답: {o.avg_ms:.0f}ms",
    ]


def errors(db: Session) -> list[str]:
    e = query_service.errors(db, RANGE, None, RECENT_ERRORS)
    if not e.errors_enabled:
        return ["오류 이벤트: 수집이 꺼져 있어 알 수 없음"]
    if not e.items:
        return ["최근 24시간 기록된 오류: 없음"]
    return [
        f"최근 24시간 오류: {i.event_type}, {i.method} {i.route}, {i.status}, {i.occurrences}회, {i.kind}"
        for i in e.items
    ]


register(
    "server_requests",
    "최근 24시간 서버 요청 수, 5xx·4xx 오류, 오류율, 평균 응답 시간.",
    requests,
    order=50,
    label="서버 요청 확인",
    area="ops",
)
register(
    "server_errors",
    "최근 24시간 오류 종류·경로·상태·횟수(최대 5개).",
    errors,
    order=60,
    label="서버 오류 확인",
    area="ops",
)
