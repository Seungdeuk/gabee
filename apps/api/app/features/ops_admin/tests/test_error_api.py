"""오류 이벤트 조회 API(/admin/ops/errors): 운영자만, 기간·종류 필터, 잘림 표시, 상세, 없는 id."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.features.ops_admin import repository
from app.features.ops_admin.models import OpsErrorEvent
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
    headers, user_id = _member(client, "ops_err_tester")
    monkeypatch.setattr(settings, "admin_user_ids", user_id)
    with SessionLocal() as db:
        db.execute(delete(OpsErrorEvent))
        db.commit()
    yield headers
    with SessionLocal() as db:
        db.execute(delete(OpsErrorEvent))
        db.commit()


def _seed(fingerprint: str, minutes_ago: int, kind: str = "server_error", **extra) -> str:
    when = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    values = {
        "fingerprint": fingerprint,
        "kind": kind,
        "severity": "error" if kind == "server_error" else "warning",
        "event_type": "ValueError" if kind == "server_error" else "token_required",
        "method": "GET",
        "route": "/items/{id}",
        "status": 500 if kind == "server_error" else 401,
        "message": "bad value [가림]" if kind == "server_error" else "",
        "location": "app/features/x/service.py:10" if kind == "server_error" else None,
        "trace_id": "abc123def4567890",
        "now": when,
        **extra,
    }
    with SessionLocal() as db:
        repository.upsert_error_event(db, **values)
    return fingerprint


def _fp(n: int) -> str:
    return f"{n:064x}"


def test_requires_login_and_operator(client, monkeypatch):
    assert client.get("/admin/ops/errors").status_code == 401
    headers, _ = _member(client, "plain_err_user")
    monkeypatch.setattr(settings, "admin_user_ids", "")
    r = client.get("/admin/ops/errors", headers=headers)
    assert r.status_code == 403 and r.json()["code"] == "operator_required"
    assert client.get(f"/admin/ops/errors/{_fp(1)}", headers=headers).status_code == 403


def test_empty_list_reports_whether_collection_is_on(client, ops, monkeypatch):
    monkeypatch.setattr(settings, "ops_errors_enabled", False)
    body = client.get("/admin/ops/errors", headers=ops).json()
    assert body["items"] == [] and body["total"] == 0 and body["truncated"] is False
    assert body["errors_enabled"] is False
    monkeypatch.setattr(settings, "ops_errors_enabled", True)
    assert client.get("/admin/ops/errors", headers=ops).json()["errors_enabled"] is True


def test_list_is_newest_first_and_hides_nothing_sensitive(client, ops):
    _seed(_fp(1), minutes_ago=30)
    _seed(_fp(2), minutes_ago=5)
    body = client.get("/admin/ops/errors?range=1h", headers=ops).json()
    assert [i["id"] for i in body["items"]] == [_fp(2), _fp(1)]
    item = body["items"][0]
    assert item["message"] == "bad value [가림]" and item["route"] == "/items/{id}"
    assert item["location"] == "app/features/x/service.py:10"
    assert item["occurrences"] == 1 and item["handling_status"] == "new"
    # 사용자·가족 id, 본문 같은 필드는 응답 모양에 없다
    assert not {"user_id", "group_id", "body", "url", "headers"} & set(item)


def test_range_excludes_older_events(client, ops):
    _seed(_fp(1), minutes_ago=30)
    _seed(_fp(2), minutes_ago=60 * 5)

    def ids(range_key: str) -> list[str]:
        r = client.get(f"/admin/ops/errors?range={range_key}", headers=ops)
        return [i["id"] for i in r.json()["items"]]

    assert ids("1h") == [_fp(1)]
    assert ids("24h") == [_fp(1), _fp(2)]
    assert ids("7d") == [_fp(1), _fp(2)]


def test_kind_filter(client, ops):
    _seed(_fp(1), 5, kind="server_error")
    _seed(_fp(2), 5, kind="auth_failure")
    only_auth = client.get("/admin/ops/errors?kind=auth_failure", headers=ops).json()["items"]
    assert [i["id"] for i in only_auth] == [_fp(2)]
    assert only_auth[0]["message"] == "" and only_auth[0]["location"] is None
    only_server = client.get("/admin/ops/errors?kind=server_error", headers=ops).json()["items"]
    assert [i["id"] for i in only_server] == [_fp(1)]
    assert len(client.get("/admin/ops/errors", headers=ops).json()["items"]) == 2


def test_limit_truncates_and_reports_total(client, ops):
    for n in range(1, 6):
        _seed(_fp(n), minutes_ago=n)
    body = client.get("/admin/ops/errors?limit=2", headers=ops).json()
    assert body["total"] == 5 and body["truncated"] is True and len(body["items"]) == 2
    assert [i["id"] for i in body["items"]] == [_fp(1), _fp(2)]  # 가장 최근 것이 남는다


def test_rejects_bad_parameters(client, ops):
    assert client.get("/admin/ops/errors?range=30d", headers=ops).status_code == 422
    assert client.get("/admin/ops/errors?kind=nope", headers=ops).status_code == 422
    assert client.get("/admin/ops/errors?limit=0", headers=ops).status_code == 422
    assert client.get("/admin/ops/errors?limit=101", headers=ops).status_code == 422


def test_detail_returns_the_event_and_counts_repeats(client, ops):
    _seed(_fp(7), minutes_ago=10)
    _seed(_fp(7), minutes_ago=1)  # 같은 지문이 다시 발생하면 한 행의 횟수가 오른다
    r = client.get(f"/admin/ops/errors/{_fp(7)}", headers=ops)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == _fp(7) and body["occurrences"] == 2
    assert body["first_seen"] < body["last_seen"]
    assert body["last_trace_id"] == "abc123def4567890"


def test_detail_unknown_or_malformed_id(client, ops):
    missing = client.get(f"/admin/ops/errors/{_fp(99)}", headers=ops)
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"
    assert client.get("/admin/ops/errors/not-a-fingerprint", headers=ops).status_code == 422
    assert client.get(f"/admin/ops/errors/{'G' * 64}", headers=ops).status_code == 422
