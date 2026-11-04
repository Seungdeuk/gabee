"""저장된 요청 지표(ops_request_metrics)를 읽어 화면용 숫자로 바꾼다. 읽기 전용이다.

저장값은 구간별 합계(요청 수, 걸린 시간 합, 최댓값)뿐이라 평균과 최댓값은 만들 수 있지만 p95 같은 백분위는 만들 수 없다.
"""

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
# 그래프 막대 하나의 길이: 길게 볼수록 굵게 묶는다
STEP: dict[str, timedelta] = {
    "1h": timedelta(minutes=5),
    "24h": timedelta(hours=1),
    "7d": timedelta(days=1),
}
MAX_ROUTES = 100


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _floor(value: datetime, step: timedelta) -> datetime:
    seconds = int(step.total_seconds())
    return datetime.fromtimestamp(int(value.timestamp()) // seconds * seconds, tz=UTC)


def _rate(part: int, total: int) -> float:
    return round(part / total, 4) if total else 0.0


def summary(db: Session, range_key: RangeKey, now: datetime | None = None) -> SummaryOut:
    now = now or datetime.now(UTC)
    since = now - RANGES[range_key]
    step = STEP[range_key]
    by_class: dict[str, int] = {}
    total_ms = peak = 0.0
    buckets: dict[datetime, list[int]] = {}
    # 빈 구간도 0 으로 채워 그래프가 끊기지 않게 한다
    t = _floor(since, step)
    while t <= now:
        buckets[t] = [0, 0]
        t += step
    for bucket_start, status_class, count, ms_sum, ms_max in repository.totals_by_bucket(db, since):
        by_class[status_class] = by_class.get(status_class, 0) + count
        total_ms += ms_sum
        peak = max(peak, ms_max)
        slot = buckets.setdefault(_floor(_utc(bucket_start), step), [0, 0])
        slot[0] += count
        if status_class == "5xx":
            slot[1] += count
    total = sum(by_class.values())
    return SummaryOut(
        range=range_key,
        since=since,
        metrics_enabled=settings.ops_metrics_enabled,
        requests=total,
        errors_5xx=by_class.get("5xx", 0),
        errors_4xx=by_class.get("4xx", 0),
        error_rate=_rate(by_class.get("5xx", 0), total),
        avg_ms=round(total_ms / total, 1) if total else 0.0,
        max_ms=round(peak, 1),
        series=[SeriesPoint(t=k, requests=v[0], errors=v[1]) for k, v in sorted(buckets.items())],
    )


def apis(db: Session, range_key: RangeKey, now: datetime | None = None) -> ApisOut:
    now = now or datetime.now(UTC)
    since = now - RANGES[range_key]
    grouped: dict[tuple[str, str], dict] = {}
    for method, route, status_class, count, ms_sum, ms_max in repository.totals_by_route(db, since):
        g = grouped.setdefault((method, route), {"n": {}, "ms": 0.0, "peak": 0.0})
        g["n"][status_class] = g["n"].get(status_class, 0) + count
        g["ms"] += ms_sum
        g["peak"] = max(g["peak"], ms_max)
    items = []
    for (method, route), g in grouped.items():
        n = g["n"]
        total = sum(n.values())
        items.append(
            ApiRouteOut(
                method=method,
                route=route,
                requests=total,
                c2xx=n.get("2xx", 0),
                c3xx=n.get("3xx", 0),
                c4xx=n.get("4xx", 0),
                c5xx=n.get("5xx", 0),
                error_rate=_rate(n.get("5xx", 0), total),
                avg_ms=round(g["ms"] / total, 1) if total else 0.0,
                max_ms=round(g["peak"], 1),
            )
        )
    items.sort(key=lambda i: (-i.requests, i.route, i.method))
    return ApisOut(
        range=range_key,
        since=since,
        metrics_enabled=settings.ops_metrics_enabled,
        items=items[:MAX_ROUTES],
    )
