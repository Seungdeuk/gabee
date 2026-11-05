"""Cloud Run 인프라 상태(읽기 전용). 새 의존성 없이 httpx 로 메타데이터 서버 토큰을 받아 Cloud Run Admin API 와 Cloud Monitoring REST 를 부른다.

설계 제안이며 실제 Cloud Run 에서는 아직 확인하지 않았다(미확인). Cloud Run 이 아니거나 꺼져 있거나 권한이 없으면 오류가 아니라
collected=false 와 이유를 돌려주고, 샘플 값을 섞지 않는다. 결과는 짧게 캐시한다. 필요한 역할: roles/run.viewer, roles/monitoring.viewer.
"""

import os
import threading
import time
from datetime import UTC, datetime, timedelta

import httpx

from app.shared.config import settings

from .schemas import InfraMetrics, InfraOut, InfraService

METADATA = "http://metadata.google.internal/computeMetadata/v1"
RUN_API = "https://run.googleapis.com/v2"
MONITORING_API = "https://monitoring.googleapis.com/v3"
CACHE_SECONDS = 60
TIMEOUT = httpx.Timeout(3.0)
WINDOW_MINUTES = 10

_lock = threading.Lock()
_cache: tuple[float, InfraOut] | None = None


class _Skip(Exception):
    """수집하지 않는 이유(사용자에게 보여 줄 짧은 문장)."""


def _off(reason: str) -> InfraOut:
    return InfraOut(collected=False, reason=reason, fetched_at=datetime.now(UTC))


def _meta(client: httpx.Client, path: str) -> dict | str:
    r = client.get(f"{METADATA}/{path}", headers={"Metadata-Flavor": "Google"})
    r.raise_for_status()
    return r.json() if path.endswith("token") else r.text


def _first_point(series: list[dict], key: str) -> float | None:
    values = []
    for s in series:
        points = s.get("points") or []
        if points:
            values.append(points[0]["value"].get(key))
    values = [v for v in values if v is not None]
    return max(values) if values else None


def _query(
    client: httpx.Client, headers: dict, project: str, service: str, metric: str, params: dict
) -> list[dict]:
    end = datetime.now(UTC)
    base = {
        "filter": (
            f'metric.type="{metric}" AND resource.type="cloud_run_revision" '
            f'AND resource.labels.service_name="{service}"'
        ),
        "interval.endTime": end.isoformat(),
        "interval.startTime": (end - timedelta(minutes=WINDOW_MINUTES)).isoformat(),
        "aggregation.alignmentPeriod": "60s",
    }
    r = client.get(
        f"{MONITORING_API}/projects/{project}/timeSeries",
        params={**base, **params},
        headers=headers,
    )
    r.raise_for_status()
    return r.json().get("timeSeries", [])


def _collect() -> InfraOut:
    service = os.environ.get("K_SERVICE")
    if not service:
        return _off("Cloud Run 에서 실행 중이 아니라 수집하지 않아요")
    with httpx.Client(timeout=TIMEOUT) as client:
        try:
            token = _meta(client, "instance/service-accounts/default/token")["access_token"]
            project = _meta(client, "project/project-id")
            region = str(_meta(client, "instance/region")).rsplit("/", 1)[-1]
        except (httpx.HTTPError, KeyError, ValueError):
            raise _Skip("실행 환경 정보를 가져오지 못했어요") from None
        headers = {"Authorization": f"Bearer {token}"}
        info = InfraService(name=service, region=region, revision=os.environ.get("K_REVISION"))
        metrics = InfraMetrics()
        errors: list[str] = []
        try:
            r = client.get(
                f"{RUN_API}/projects/{project}/locations/{region}/services/{service}",
                headers=headers,
            )
            r.raise_for_status()
            body = r.json()
            tmpl = body.get("template") or {}
            scaling = tmpl.get("scaling") or body.get("scaling") or {}
            info.min_instances = scaling.get("minInstanceCount") or scaling.get("minInstances")
            info.max_instances = scaling.get("maxInstanceCount") or scaling.get("maxInstances")
            containers = tmpl.get("containers") or [{}]
            idle = (containers[0].get("resources") or {}).get("cpuIdle")
            info.cpu_allocation = None if idle is None else ("request" if idle else "instance")
        except httpx.HTTPError as e:
            errors.append(_http_reason("Cloud Run 설정", e))
        try:
            series = _query(
                client,
                headers,
                project,
                service,
                "run.googleapis.com/container/instance_count",
                {
                    "aggregation.perSeriesAligner": "ALIGN_MAX",
                    "aggregation.crossSeriesReducer": "REDUCE_SUM",
                    "aggregation.groupByFields": "metric.labels.state",
                },
            )
            for s in series:
                state = (s.get("metric") or {}).get("labels", {}).get("state")
                value = _first_point([s], "int64Value")
                if value is not None:
                    value = int(value)
                if state == "active":
                    metrics.instances_active = value
                elif state == "idle":
                    metrics.instances_idle = value
            for field, metric in (
                ("cpu_p99", "run.googleapis.com/container/cpu/utilizations"),
                ("memory_p99", "run.googleapis.com/container/memory/utilizations"),
            ):
                series = _query(
                    client,
                    headers,
                    project,
                    service,
                    metric,
                    {
                        "aggregation.perSeriesAligner": "ALIGN_PERCENTILE_99",
                        "aggregation.crossSeriesReducer": "REDUCE_MAX",
                    },
                )
                setattr(metrics, field, _first_point(series, "doubleValue"))
        except httpx.HTTPError as e:
            errors.append(_http_reason("Cloud Monitoring", e))
    if len(errors) == 2:
        raise _Skip(" / ".join(errors))
    return InfraOut(
        collected=True,
        reason=" / ".join(errors) or None,
        service=info,
        metrics=metrics,
        window_minutes=WINDOW_MINUTES,
        fetched_at=datetime.now(UTC),
    )


def _http_reason(what: str, e: httpx.HTTPError) -> str:
    status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
    if status in (401, 403):
        return f"{what} 조회 권한이 없어요"
    if status == 404:
        return f"{what}을(를) 찾지 못했어요"
    return f"{what}을(를) 가져오지 못했어요"


def get_infra() -> InfraOut:
    """수집 결과(60초 캐시). 어떤 실패도 예외로 올리지 않는다."""
    global _cache
    if not settings.ops_infra_enabled:
        return _off("수집이 꺼져 있어요(OPS_INFRA_ENABLED)")
    with _lock:
        if _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
            return _cache[1]
        try:
            result = _collect()
        except _Skip as e:
            result = _off(str(e))
        except Exception:  # 인프라 조회 실패가 화면 전체를 막으면 안 된다
            result = _off("인프라 정보를 가져오지 못했어요")
        _cache = (time.monotonic(), result)
        return result
