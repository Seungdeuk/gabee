"""요청 계측: 기본 꺼짐, trace id, 경로 패턴만 집계, 개인정보 미저장, 실패해도 요청 무영향, 구간 저장·보관 정리."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.features.ops_admin import repository, service
from app.features.ops_admin.middleware import RequestMetricsMiddleware
from app.features.ops_admin.models import OpsRequestMetric
from app.shared.config import settings
from app.shared.db import SessionLocal

CANCEL = "/family-group/groups/join-requests/{}/cancel"  # 인증이 없으면 401 인 경로 패턴 하나


@pytest.fixture
def metrics(monkeypatch):
    """지표를 켜고 집계를 비운 상태로 시작한다."""
    monkeypatch.setattr(settings, "ops_metrics_enabled", True)
    service.aggregator.reset()
    yield service.aggregator
    service.aggregator.reset()


def _rows() -> list[OpsRequestMetric]:
    with SessionLocal() as db:
        return list(db.scalars(select(OpsRequestMetric)))


def test_disabled_by_default_adds_no_header_and_records_nothing(client):
    service.aggregator.reset()
    r = client.get("/family-group/auth/me")
    assert r.status_code == 401
    assert "x-trace-id" not in r.headers
    assert service.aggregator.take() == []


def test_enabled_sets_a_new_trace_id_per_request(client, metrics):
    first = client.get("/family-group/auth/me")
    second = client.get("/family-group/auth/me")
    a, b = first.headers["x-trace-id"], second.headers["x-trace-id"]
    assert len(a) == 16 and a != b


def test_route_pattern_is_recorded_not_the_raw_url(client, metrics):
    client.post(CANCEL.format("secret-request-id-123"), params={"token": "very-secret"})
    rows = metrics.take()
    assert len(rows) == 1
    bucket, method, route, klass, count, total, peak = rows[0]
    assert route == CANCEL.format("{request_id}") and method == "POST" and klass == "4xx"
    assert count == 1 and total >= 0 and peak >= 0
    assert "secret" not in repr(rows)  # 주소 값·쿼리 값은 어디에도 없다


def test_unmatched_requests_share_one_name_without_the_raw_path(client, metrics):
    client.get("/no/such/path/with-private-name")
    rows = metrics.take()
    assert [(r[1], r[2], r[3]) for r in rows] == [("GET", "unmatched", "4xx")]
    assert "private" not in repr(rows)


def test_health_checks_are_not_counted(client, metrics):
    client.get("/health")
    client.get("/health/db")
    assert metrics.take() == []


def test_unhandled_exception_is_counted_as_5xx():
    app = FastAPI()
    app.add_middleware(RequestMetricsMiddleware)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret detail")

    settings.ops_metrics_enabled = True
    try:
        service.aggregator.reset()
        r = TestClient(app, raise_server_exceptions=False).get("/boom")
        assert r.status_code == 500
        rows = service.aggregator.take()
    finally:
        settings.ops_metrics_enabled = False
        service.aggregator.reset()
    assert [(x[1], x[2], x[3]) for x in rows] == [("GET", "/boom", "5xx")]
    assert "secret" not in repr(rows)  # 예외 메시지는 집계에 들어가지 않는다


def test_failing_record_does_not_affect_the_request(client, metrics, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("metrics down")

    monkeypatch.setattr(service.aggregator, "record", broken)
    r = client.get("/family-group/auth/me")
    assert r.status_code == 401 and "x-trace-id" in r.headers


def test_failing_flush_drops_the_batch_and_does_not_raise(client, metrics, monkeypatch):
    client.get("/family-group/auth/me")

    def broken(db, rows):
        raise RuntimeError("db down")

    monkeypatch.setattr(repository, "upsert_rows", broken)
    metrics.flush(final=True)  # 예외가 밖으로 나오지 않는다
    assert metrics.take() == []  # 실패한 묶음은 쌓아 두지 않고 버린다


def test_flush_saves_aggregates_and_adds_to_existing_rows(client, metrics):
    client.get("/family-group/auth/me")
    client.get("/family-group/auth/me")
    metrics.flush(final=True)
    client.get("/family-group/auth/me")
    metrics.flush(final=True)  # 같은 구간의 같은 키: 더해진다
    rows = [r for r in _rows() if r.route == "/family-group/auth/me"]
    assert len(rows) == 1
    assert rows[0].request_count == 3 and rows[0].status_class == "4xx"
    assert rows[0].duration_ms_max <= rows[0].duration_ms_sum


def test_new_bucket_flushes_the_previous_one(client):
    clock = {"now": 1_000_000.0}
    agg = service.MetricsAggregator(clock=lambda: clock["now"])
    old_bucket = int(clock["now"]) // 300 * 300
    assert agg.record("GET", "/a", 200, 10.0) is None
    clock["now"] += 301  # 다음 구간
    due = agg.record("GET", "/a", 500, 30.0)
    assert due and all(k[0] == datetime.fromtimestamp(old_bucket, tz=UTC) for k in due)
    agg.flush()  # 지난 구간만 저장, 현재 구간은 남는다
    saved = [r for r in _rows() if r.route == "/a"]
    assert [(r.status_class, r.request_count) for r in saved] == [("2xx", 1)]
    assert [(r[3], r[4]) for r in agg.take()] == [("5xx", 1)]


def test_unknown_methods_are_grouped():
    agg = service.MetricsAggregator(clock=lambda: 1_000_000.0)
    agg.record("BREW", "/a", 200, 1.0)
    assert [r[1] for r in agg.take()] == ["OTHER"]


def test_old_rows_are_purged_after_the_retention_period(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        repository.upsert_rows(
            db,
            [
                (now - timedelta(days=91), "GET", "/old", "2xx", 1, 5.0, 5.0),
                (now - timedelta(days=1), "GET", "/new", "2xx", 1, 5.0, 5.0),
            ],
        )
        removed = repository.delete_before(
            db, now - timedelta(days=settings.ops_metrics_retention_days)
        )
    assert removed == 1
    assert [r.route for r in _rows()] == ["/new"]


def test_the_table_has_no_column_for_personal_data():
    columns = {c.name for c in OpsRequestMetric.__table__.columns}
    assert columns == {
        "bucket_start",
        "method",
        "route",
        "status_class",
        "request_count",
        "duration_ms_sum",
        "duration_ms_max",
    }
