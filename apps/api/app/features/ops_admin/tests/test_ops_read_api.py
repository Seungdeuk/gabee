"""운영 조회 API: 운영자만 접근, 기간별 합산, 경로 패턴 단위 집계, 데이터가 없을 때의 응답. 가짜 계정·가짜 지표만 쓴다."""

from datetime import UTC, datetime, timedelta

import pytest

from app.features.ops_admin import repository
from app.shared.config import settings
from app.shared.db import SessionLocal

SIGNUP = "/family-group/auth/signup"
LOGIN = "/family-group/auth/login"
PASSWORD = "Sunny-day-2026"


def _member(client, login_id: str) -> tuple[dict, str]:
    body = {
        "login_id": login_id,
        "password": PASSWORD,
        "email": f"{login_id}@example.com",
        "name": "시험",
    }
    assert client.post(SIGNUP, json=body).status_code == 201
    r = client.post(LOGIN, json={"login_id": login_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]["id"]


@pytest.fixture
def ops(client, monkeypatch):
    """운영자로 허용된 계정의 헤더."""
    headers, user_id = _member(client, "ops_tester")
    monkeypatch.setattr(settings, "ops_admin_user_ids", user_id)
    return headers


def _seed(rows):
    with SessionLocal() as db:
        repository.upsert_rows(db, rows)


def _bucket(minutes_ago: int) -> datetime:
    t = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return t.replace(second=0, microsecond=0)


def test_requires_login_and_operator(client, monkeypatch):
    assert client.get("/admin/ops/summary").status_code == 401
    headers, _ = _member(client, "plain_user")
    monkeypatch.setattr(settings, "ops_admin_user_ids", "")
    r = client.get("/admin/ops/summary", headers=headers)
    assert r.status_code == 403 and r.json()["code"] == "operator_required"
    assert client.get("/admin/ops/apis", headers=headers).status_code == 403


def test_empty_data_returns_zeros_and_flag(client, ops, monkeypatch):
    monkeypatch.setattr(settings, "ops_metrics_enabled", False)
    r = client.get("/admin/ops/summary?range=1h", headers=ops)
    assert r.status_code == 200
    body = r.json()
    assert body["requests"] == 0 and body["error_rate"] == 0 and body["avg_ms"] == 0
    assert body["metrics_enabled"] is False
    assert len(body["series"]) >= 12  # 5분 단위로 빈 구간도 채운다
    assert client.get("/admin/ops/apis", headers=ops).json()["items"] == []


def test_summary_sums_and_error_rate(client, ops):
    _seed(
        [
            (_bucket(10), "GET", "/items/{id}", "2xx", 90, 900.0, 40.0),
            (_bucket(10), "GET", "/items/{id}", "5xx", 10, 500.0, 120.0),
            (_bucket(20), "POST", "/items", "4xx", 5, 50.0, 15.0),
        ]
    )
    body = client.get("/admin/ops/summary?range=1h", headers=ops).json()
    assert body["requests"] == 105 and body["errors_5xx"] == 10 and body["errors_4xx"] == 5
    assert body["error_rate"] == round(10 / 105, 4)
    assert body["avg_ms"] == round(1450 / 105, 1) and body["max_ms"] == 120.0
    assert sum(p["requests"] for p in body["series"]) == 105
    assert sum(p["errors"] for p in body["series"]) == 10


def test_range_excludes_older_buckets(client, ops):
    _seed([(_bucket(180), "GET", "/old", "2xx", 7, 70.0, 10.0)])
    assert client.get("/admin/ops/summary?range=1h", headers=ops).json()["requests"] == 0
    assert client.get("/admin/ops/summary?range=24h", headers=ops).json()["requests"] == 7
    assert client.get("/admin/ops/summary?range=7d", headers=ops).json()["requests"] == 7


def test_apis_group_by_route_pattern_sorted_by_requests(client, ops):
    _seed(
        [
            (_bucket(5), "GET", "/a/{id}", "2xx", 8, 80.0, 20.0),
            (_bucket(5), "GET", "/a/{id}", "5xx", 2, 40.0, 60.0),
            (_bucket(15), "GET", "/a/{id}", "2xx", 10, 100.0, 30.0),
            (_bucket(5), "POST", "/b", "2xx", 3, 30.0, 12.0),
        ]
    )
    items = client.get("/admin/ops/apis?range=1h", headers=ops).json()["items"]
    assert [(i["method"], i["route"]) for i in items] == [("GET", "/a/{id}"), ("POST", "/b")]
    a = items[0]
    assert a["requests"] == 20 and a["c2xx"] == 18 and a["c5xx"] == 2
    assert a["error_rate"] == 0.1 and a["avg_ms"] == 11.0 and a["max_ms"] == 60.0


def test_rejects_unknown_range(client, ops):
    assert client.get("/admin/ops/summary?range=30d", headers=ops).status_code == 422


def test_window_start_is_aligned_so_the_oldest_partial_bucket_is_kept(client, monkeypatch):
    from app.features.ops_admin import query_service

    monkeypatch.setattr(settings, "ops_metrics_bucket_seconds", 300)
    now = datetime(2026, 11, 4, 12, 3, tzinfo=UTC)
    # 12:03 기준 1시간 전은 11:03 이고, 11:00 구간(11:00~11:05)은 그 일부가 창에 걸쳐 있으므로 포함해야 한다
    _seed([(datetime(2026, 11, 4, 11, 0, tzinfo=UTC), "GET", "/edge", "2xx", 4, 40.0, 15.0)])
    _seed([(datetime(2026, 11, 4, 10, 55, tzinfo=UTC), "GET", "/older", "2xx", 9, 90.0, 15.0)])
    with SessionLocal() as db:
        out = query_service.summary(db, "1h", now=now)
        routes = query_service.apis(db, "1h", now=now)
    assert out.requests == 4 and out.since == datetime(2026, 11, 4, 11, 0, tzinfo=UTC)
    assert [i.route for i in routes.items] == ["/edge"]


def test_chart_step_is_never_finer_than_the_stored_bucket(client, monkeypatch):
    from app.features.ops_admin import query_service

    monkeypatch.setattr(settings, "ops_metrics_bucket_seconds", 900)  # 15분
    now = datetime(2026, 11, 4, 12, 3, tzinfo=UTC)
    _seed([(datetime(2026, 11, 4, 11, 45, tzinfo=UTC), "GET", "/x", "2xx", 6, 60.0, 15.0)])
    with SessionLocal() as db:
        out = query_service.summary(db, "1h", now=now)
    gaps = {(b.t - a.t).total_seconds() for a, b in zip(out.series, out.series[1:], strict=False)}
    assert gaps == {900.0}  # 5분 막대로 쪼개지 않는다
    assert sum(p.requests for p in out.series) == 6


def test_apis_reports_truncation(client, monkeypatch):
    from app.features.ops_admin import query_service

    monkeypatch.setattr(query_service, "MAX_ROUTES", 2)
    _seed([(_bucket(5), "GET", f"/r{i}", "2xx", i + 1, 1.0, 1.0) for i in range(3)])
    body = client.get("/admin/ops/apis?range=1h", headers=_ops_headers(client, monkeypatch)).json()
    assert body["total_routes"] == 3 and body["truncated"] is True and len(body["items"]) == 2
    assert [i["route"] for i in body["items"]] == ["/r2", "/r1"]  # 요청 수가 많은 쪽이 남는다


def _ops_headers(client, monkeypatch) -> dict:
    headers, user_id = _member(client, "ops_tester2")
    monkeypatch.setattr(settings, "ops_admin_user_ids", user_id)
    return headers
