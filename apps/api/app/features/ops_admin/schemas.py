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
    range: RangeKey
    since: datetime
    metrics_enabled: bool
    items: list[ApiRouteOut]
