"""요청 지표 집계(메모리) → 구간이 바뀔 때 DB 에 저장.

수집하는 것은 요청의 메서드, 경로 패턴, 상태코드 구분, 걸린 시간뿐이다. URL 원문·본문·쿼리·헤더·사용자 id 는 받지도 않는다.
계측은 요청을 느리게 하거나 실패하게 만들면 안 된다: 저장에 실패하면 그 구간의 집계만 버리고 로그에 예외 클래스 이름만 남긴다.

Cloud Run 은 요청이 없을 때 CPU 를 줄일 수 있어서(미확인) 백그라운드 타이머를 쓰지 않고, 새 구간의 첫 요청이 지난 구간을
저장한다. 인스턴스가 여러 개여도 저장은 같은 키의 행에 더하므로 합계가 맞는다.
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.shared.config import settings
from app.shared.db import SessionLocal

from . import repository

logger = logging.getLogger(__name__)

UNMATCHED = "unmatched"  # 어떤 라우트와도 맞지 않은 요청(404 등). 원본 주소를 남기지 않으려 한 이름으로 묶는다
KNOWN_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
EXCLUDED_PREFIXES = (
    "/health",  # 상태 확인 호출은 지표를 부풀리므로 제외한다
    "/admin/ops/",  # 운영 화면이 자동 갱신으로 부르는 조회가 자기 지표를 부풀리지 않게 한다
)
MAX_ROUTE_LENGTH = 200
PURGE_EVERY_SECONDS = 3600

Key = tuple[datetime, str, str, str]  # (구간 시작, 메서드, 경로 패턴, 상태코드 구분)


def status_class(status: int) -> str:
    return f"{status // 100}xx" if 100 <= status < 600 else "5xx"


def normalize_route(route_path: str | None) -> str:
    """라우트 패턴을 그대로 쓰되 없으면 unmatched, 너무 길면 자른다."""
    if not route_path:
        return UNMATCHED
    return route_path[:MAX_ROUTE_LENGTH]


def route_template(scope: dict) -> str | None:
    """요청의 경로 패턴(`/family-group/groups/{group_id}`). 맞는 라우트가 없으면 None.

    중첩 라우터에서는 라우트가 자기 몫의 패턴만 갖고 있어서(앞의 접두사 `/family-group` 이 빠진다), 실제 경로에서
    그 패턴에 해당하는 끝부분을 떼어 낸 나머지를 접두사로 붙인다. 접두사에는 주소 값이 들어 있지 않아야 하며,
    확신할 수 없으면 라우트 자신의 패턴만 쓴다."""
    route = scope.get("route")
    pattern = getattr(route, "path_format", None) or getattr(route, "path", None)
    if not pattern:
        return None
    params = {str(k): str(v) for k, v in (scope.get("path_params") or {}).items()}
    actual = pattern
    for name, value in params.items():
        actual = actual.replace("{" + name + "}", value)
    full = scope.get("path") or ""
    if not full.endswith(actual):
        return pattern
    prefix = full[: len(full) - len(actual)]
    if any(value and value in prefix for value in params.values()):
        return pattern
    return prefix + pattern


def is_excluded(route: str) -> bool:
    return route.startswith(EXCLUDED_PREFIXES)


class MetricsAggregator:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[Key, list[float]] = {}  # 키 → [횟수, 시간 합(ms), 시간 최댓값(ms)]
        self._last_purge = 0.0

    def _bucket_start(self, now: float) -> datetime:
        size = max(int(settings.ops_metrics_bucket_seconds), 1)
        return datetime.fromtimestamp(int(now) // size * size, tz=UTC)

    def record(self, method: str, route: str, status: int, duration_ms: float) -> list[Key] | None:
        """한 요청을 집계에 더한다. 새 구간으로 넘어갔으면 저장해야 할 이전 구간의 키 목록을 돌려준다."""
        if is_excluded(route):
            return None
        method = method.upper() if method.upper() in KNOWN_METHODS else "OTHER"
        now = self._bucket_start(self._clock())
        key = (now, method, route, status_class(status))
        with self._lock:
            slot = self._buckets.setdefault(key, [0, 0.0, 0.0])
            slot[0] += 1
            slot[1] += duration_ms
            slot[2] = max(slot[2], duration_ms)
            return [k for k in self._buckets if k[0] < now] or None

    def take(self, only_before: datetime | None = None) -> list[repository.Row]:
        """저장할 행을 꺼내고 집계에서 지운다. only_before 가 있으면 그보다 이른 구간만 꺼낸다."""
        with self._lock:
            keys = [k for k in self._buckets if only_before is None or k[0] < only_before]
            rows = [
                (*k, int(self._buckets[k][0]), self._buckets[k][1], self._buckets[k][2])
                for k in keys
            ]
            for k in keys:
                del self._buckets[k]
        return rows

    def flush(self, final: bool = False) -> None:
        """지난 구간(final=True 면 전부)을 DB 에 저장한다. 실패해도 예외를 밖으로 내지 않는다."""
        rows = self.take(None if final else self._bucket_start(self._clock()))
        if not rows:
            return
        try:
            with SessionLocal() as db:
                repository.upsert_rows(db, rows)
                self._purge_if_due(db)
        except Exception as exc:  # 계측 실패가 요청에 영향을 주면 안 된다
            logger.warning("ops metrics flush failed: %s", type(exc).__name__)

    def _purge_if_due(self, db) -> None:
        now = self._clock()
        if now - self._last_purge < PURGE_EVERY_SECONDS:
            return
        self._last_purge = now
        cutoff = datetime.fromtimestamp(now, tz=UTC) - timedelta(
            days=settings.ops_metrics_retention_days
        )
        repository.delete_before(db, cutoff)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
        self._last_purge = 0.0


aggregator = MetricsAggregator()
