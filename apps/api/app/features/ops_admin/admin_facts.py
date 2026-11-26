"""운영 숫자(서버 요청·오류)를 관리자 챗봇 명단(shared/admin_facts)에 올린다.

오류는 종류·경로·상태·횟수만 담는다. 오류 message 와 trace id 는 쓰지 않는다.
수집이 꺼져 있으면 0 이 진짜 0 이 아니므로 '알 수 없음'으로 보낸다.
"""

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.shared.admin_facts import register

from . import cloud_status, query_service

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


class Hours(BaseModel):
    """오류 로그를 셀 기간. Claude 가 질문을 보고 채운다."""

    hours: int = Field(
        default=24, ge=1, le=cloud_status.MAX_HOURS, description="최근 몇 시간(1~72, 기본 24)"
    )


def cloud_traffic(db: Session) -> list[str]:
    return cloud_status.traffic()


def cloud_revisions(db: Session) -> list[str]:
    return cloud_status.revisions()


def cloud_error_logs(db: Session, hours: int = 24) -> list[str]:
    return cloud_status.error_logs(hours)


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
register(
    "cloud_traffic",
    "Cloud Run 배포 상태: 지금 트래픽이 어느 버전으로 몇 % 가는지(고정 여부·태그), 최신 정상 버전, 서비스 정상 여부. "
    "'지금 배포된 버전', '트래픽 어디로 가', '새 버전 반영됐어' 같은 질문에 쓴다.",
    cloud_traffic,
    order=62,
    label="배포·트래픽 확인",
    area="ops",
)
register(
    "cloud_revisions",
    "Cloud Run 최근 버전 최대 5개: 이름, 만든 시각(한국 시간), 정상 여부. '최근 배포 언제 했어' 같은 질문에 쓴다.",
    cloud_revisions,
    order=64,
    label="최근 버전 확인",
    area="ops",
)
register(
    "cloud_error_logs",
    "Cloud Run 오류(ERROR 이상) 로그 건수를 최근 N시간(기본 24, 최대 72) 동안 버전별·응답 코드별로 센다. "
    "로그 내용은 없고 건수만 준다. '오늘 오류 몇 건', '새 버전에서 오류 나?' 같은 질문에 쓴다.",
    cloud_error_logs,
    order=66,
    params=Hours,
    label="오류 로그 확인",
    area="ops",
)
