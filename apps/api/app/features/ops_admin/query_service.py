"""저장된 요청 지표(ops_request_metrics)를 읽어 화면용 숫자로 바꾼다. 읽기 전용이다.

저장값은 구간별 합계(요청 수, 걸린 시간 합, 최댓값)뿐이라 평균과 최댓값은 만들 수 있지만 p95 같은 백분위는 만들 수 없다.
알려진 한계: DB 에 저장된 구간만 읽는다. 아직 닫히지 않은 최신 구간(메모리 집계)은 구간이 바뀐 뒤에 보인다.
평균 응답 시간은 모든 상태코드 구분을 합친 값이다.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.shared.config import settings

from . import repository
from .schemas import ApiRouteOut, ApisOut, RangeKey, SeriesPoint, SummaryOut

RANGES: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}
# 그래프 막대 하나의 길이(최소값): 길게 볼수록 굵게 묶는다. 저장 구간이 더 길면 저장 구간 길이를 쓴다
STEP: dict[str, timedelta] = {
    "1h": timedelta(minutes=5),
    "24h": timedelta(hours=1),
    "7d": timedelta(days=1),
}
MAX_ROUTES = 100


@dataclass
class _Acc:
    """상태코드 구분별 건수와 걸린 시간 합·최댓값을 모으는 그릇."""

    by_class: dict[str, int] = field(default_factory=dict)
    ms_sum: float = 0.0
    ms_max: float = 0.0

    def add(self, status_class: str, count: int, ms_sum: float, ms_max: float) -> None:
        self.by_class[status_class] = self.by_class.get(status_class, 0) + count
        self.ms_sum += ms_sum
        self.ms_max = max(self.ms_max, ms_max)

    @property
    def total(self) -> int:
        return sum(self.by_class.values())

    def n(self, status_class: str) -> int:
        return self.by_class.get(status_class, 0)

    @property
    def avg(self) -> float:
        return round(self.ms_sum / self.total, 1) if self.total else 0.0


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _floor(value: datetime, step: timedelta) -> datetime:
    seconds = int(step.total_seconds())
    return datetime.fromtimestamp(int(value.timestamp()) // seconds * seconds, tz=UTC)


def _rate(part: int, total: int) -> float:
    return round(part / total, 4) if total else 0.0


def _window(range_key: str, now: datetime) -> tuple[datetime, timedelta]:
    """조회 시작 시각과 그래프 간격. 시작은 저장 구간 경계로 내려서 가장 오래된 부분 구간이 빠지지 않게 한다."""
    bucket = timedelta(seconds=max(1, settings.ops_metrics_bucket_seconds))
    step = max(STEP[range_key], bucket)
    return _floor(now - RANGES[range_key], bucket), step


def summary(db: Session, range_key: RangeKey, now: datetime | None = None) -> SummaryOut:
    now = now or datetime.now(UTC)
    since, step = _window(range_key, now)
    total = _Acc()
    # 빈 구간도 0 으로 채워 그래프가 끊기지 않게 한다. 값은 [요청 수, 5xx]
    series: dict[datetime, list[int]] = {}
    t = _floor(since, step)
    while t <= now:
        series[t] = [0, 0]
        t += step
    for bucket_start, status_class, count, ms_sum, ms_max in repository.totals_by_bucket(db, since):
        total.add(status_class, count, ms_sum, ms_max)
        slot = series.setdefault(_floor(_utc(bucket_start), step), [0, 0])
        slot[0] += count
        if status_class == "5xx":
            slot[1] += count
    return SummaryOut(
        range=range_key,
        since=since,
        metrics_enabled=settings.ops_metrics_enabled,
        requests=total.total,
        errors_5xx=total.n("5xx"),
        errors_4xx=total.n("4xx"),
        error_rate=_rate(total.n("5xx"), total.total),
        avg_ms=total.avg,
        max_ms=round(total.ms_max, 1),
        series=[SeriesPoint(t=k, requests=v[0], errors=v[1]) for k, v in sorted(series.items())],
    )


def apis(db: Session, range_key: RangeKey, now: datetime | None = None) -> ApisOut:
    now = now or datetime.now(UTC)
    since, _ = _window(range_key, now)
    grouped: dict[tuple[str, str], _Acc] = {}
    for method, route, status_class, count, ms_sum, ms_max in repository.totals_by_route(db, since):
        grouped.setdefault((method, route), _Acc()).add(status_class, count, ms_sum, ms_max)
    items = [
        ApiRouteOut(
            method=method,
            route=route,
            requests=acc.total,
            c2xx=acc.n("2xx"),
            c3xx=acc.n("3xx"),
            c4xx=acc.n("4xx"),
            c5xx=acc.n("5xx"),
            error_rate=_rate(acc.n("5xx"), acc.total),
            avg_ms=acc.avg,
            max_ms=round(acc.ms_max, 1),
        )
        for (method, route), acc in grouped.items()
    ]
    items.sort(key=lambda i: (-i.requests, i.route, i.method))
    return ApisOut(
        range=range_key,
        since=since,
        metrics_enabled=settings.ops_metrics_enabled,
        total_routes=len(items),
        truncated=len(items) > MAX_ROUTES,
        items=items[:MAX_ROUTES],
    )
