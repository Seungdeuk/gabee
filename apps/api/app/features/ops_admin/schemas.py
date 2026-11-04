"""운영 관리자 조회 API 의 응답 모양. 집계 숫자와 경로 패턴만 담고, 사용자·가족 id 나 요청 내용은 담지 않는다."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

RangeKey = Literal["1h", "24h", "7d"]


class SeriesPoint(BaseModel):
    t: datetime  # 구간 시작(UTC)
    requests: int
    errors: int  # 5xx


class SummaryOut(BaseModel):
    range: RangeKey
    since: datetime
    metrics_enabled: bool  # 계측이 꺼져 있으면 숫자가 0 인 이유를 화면이 설명할 수 있다
    requests: int
    errors_5xx: int
    errors_4xx: int
    error_rate: float  # 5xx / 전체, 요청이 없으면 0
    avg_ms: float
    max_ms: float
    series: list[SeriesPoint]


class ApiRouteOut(BaseModel):
    method: str
    route: str  # 경로 패턴 (`/family-group/groups/{group_id}`) 또는 unmatched
    requests: int
    c2xx: int
    c3xx: int
    c4xx: int
    c5xx: int
    error_rate: float
    avg_ms: float
    max_ms: float


class ApisOut(BaseModel):
    total_routes: int  # 잘리기 전의 전체 경로 수
    truncated: bool  # items 가 최대 개수에서 잘렸는지
    range: RangeKey
    since: datetime
    metrics_enabled: bool
    items: list[ApiRouteOut]


ErrorKind = Literal["server_error", "auth_failure"]


class ErrorEventOut(BaseModel):
    """오류 이벤트 하나(같은 지문의 발생을 합친 기록). 메시지는 이미 가린 값이고 인증 실패는 메시지가 비어 있다."""

    id: str  # 지문(fingerprint)
    kind: ErrorKind
    severity: str  # error | warning
    event_type: str  # 예외 클래스 이름 또는 응답 code
    method: str
    route: str  # 경로 패턴 또는 unmatched
    status: int
    message: str
    location: str | None  # app/...py:줄
    occurrences: int
    first_seen: datetime
    last_seen: datetime
    last_trace_id: str | None
    handling_status: str
    assignee_label: str | None
    note: str | None


class ErrorListOut(BaseModel):
    range: RangeKey
    since: datetime
    errors_enabled: bool  # 수집이 꺼져 있으면 목록이 비어 있는 이유를 화면이 설명할 수 있다
    total: int  # 조건에 맞는 전체 수(잘리기 전)
    truncated: bool  # items 가 limit 에서 잘렸는지
    items: list[ErrorEventOut]
