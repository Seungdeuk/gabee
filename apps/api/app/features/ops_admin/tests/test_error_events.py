"""운영 오류 이벤트: 5xx·처리되지 않은 예외·401/403 만 지문별로 합쳐 저장하고, 개인정보와 응답 영향이 없는지 확인한다."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.features.ops_admin import error_service, repository
from app.features.ops_admin.models import OpsErrorEvent
from app.main import app
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.errors import ApiError

SIGNUP = "/family-group/auth/signup"
LOGIN = "/family-group/auth/login"
PASSWORD = "Sunny-day-2026"


def _boom():
    raise ValueError("save failed for someone@example.com id 777f3f5a4e00")


def _unavailable():
    raise ApiError(503, "llm_unavailable", "model down, contact 010-1234-5678")


@pytest.fixture
def quiet_client():
    """500 을 예외로 올리지 않고 응답으로 받는 클라이언트와, 시험용 경로."""
    app.add_api_route("/__test/boom", _boom, methods=["GET"])
    app.add_api_route("/__test/unavailable", _unavailable, methods=["GET"])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.router.routes[:] = [
        r for r in app.router.routes if not getattr(r, "path", "").startswith("/__test/")
    ]


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "ops_errors_enabled", True)
    monkeypatch.setattr(error_service, "_last_purge", 0.0)
    with SessionLocal() as db:
        db.execute(delete(OpsErrorEvent))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(OpsErrorEvent))
        db.commit()


def _events() -> list[OpsErrorEvent]:
    with SessionLocal() as db:
        return list(db.scalars(select(OpsErrorEvent).order_by(OpsErrorEvent.first_seen)))


def test_disabled_by_default_stores_nothing(quiet_client):
    assert settings.ops_errors_enabled is False
    with SessionLocal() as db:
        db.execute(delete(OpsErrorEvent))
        db.commit()
    assert quiet_client.get("/__test/boom").status_code == 500
    assert _events() == []


def test_unhandled_exception_uses_common_error_format_and_hides_details(quiet_client, enabled):
    r = quiet_client.get("/__test/boom")
    assert r.status_code == 500
    assert r.json() == {"code": "internal_error", "message": "서버에 문제가 생겼어요"}
    assert "someone@example.com" not in r.text


def test_unhandled_exception_is_stored_with_masked_message_and_location(quiet_client, enabled):
    quiet_client.get("/__test/boom")
    (e,) = _events()
    assert (e.kind, e.severity, e.status) == ("server_error", "error", 500)
    assert (e.event_type, e.method, e.route) == ("ValueError", "GET", "/__test/boom")
    assert "someone@example.com" not in e.message and "777f3f5a4e00" not in e.message
    assert e.message.startswith("save failed for")
    assert e.location and e.location.startswith("app/") and "test_error_events.py:" in e.location
    assert e.occurrences == 1 and e.handling_status == "new"


def test_same_error_is_merged_into_one_row_with_a_count(quiet_client, enabled):
    for _ in range(3):
        quiet_client.get("/__test/boom")
    (e,) = _events()
    assert e.occurrences == 3
    assert e.last_seen >= e.first_seen


def test_api_error_5xx_is_stored_by_response_code_with_masked_message(quiet_client, enabled):
    r = quiet_client.get("/__test/unavailable")
    assert r.status_code == 503 and r.json()["code"] == "llm_unavailable"
    (e,) = _events()
    assert (e.event_type, e.status, e.kind) == ("llm_unavailable", 503, "server_error")
    assert "010-1234-5678" not in e.message
    assert e.location is None  # ApiError 는 던진 곳이 아니라 응답 코드로 묶는다


def test_auth_failures_store_only_the_code_and_no_message(client, enabled, monkeypatch):
    assert client.get("/admin/ops/summary").status_code == 401
    body = {
        "login_id": "plain_user",
        "password": PASSWORD,
        "email": "plain_user@example.com",
        "name": "시험",
    }
    assert client.post(SIGNUP, json=body).status_code == 201
    token = client.post(LOGIN, json={"login_id": "plain_user", "password": PASSWORD}).json()
    monkeypatch.setattr(settings, "admin_user_ids", "")
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    assert client.get("/admin/ops/summary", headers=headers).status_code == 403

    events = {e.status: e for e in _events()}
    assert set(events) == {401, 403}
    for e in events.values():
        assert (e.kind, e.severity, e.message, e.location) == ("auth_failure", "warning", "", None)
        assert e.route == "/admin/ops/summary"
    assert events[403].event_type == "operator_required"
    assert "plain_user" not in repr([(e.event_type, e.message, e.route) for e in events.values()])


def test_other_client_errors_are_not_stored(client, enabled):
    assert client.get("/no/such/route").status_code == 404
    assert client.get("/admin/ops/summary?range=bad").status_code in (401, 422)
    assert [e.status for e in _events() if e.status not in (401, 403)] == []


def test_recording_failure_does_not_change_the_response(quiet_client, enabled, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("db is down")

    monkeypatch.setattr(repository, "upsert_error_event", boom)
    r = quiet_client.get("/__test/boom")
    assert r.status_code == 500 and r.json()["code"] == "internal_error"


def test_trace_id_is_kept_when_metrics_are_on(quiet_client, enabled, monkeypatch):
    monkeypatch.setattr(settings, "ops_metrics_enabled", True)
    r = quiet_client.get("/__test/boom")
    trace = r.headers.get("x-trace-id")
    assert trace
    (e,) = _events()
    assert e.last_trace_id == trace


def test_old_events_are_purged_after_the_retention_period(quiet_client, enabled, monkeypatch):
    old = datetime.now(UTC) - timedelta(days=settings.ops_errors_retention_days + 5)
    with SessionLocal() as db:
        repository.upsert_error_event(
            db,
            fingerprint="old",
            kind="server_error",
            severity="error",
            event_type="OldError",
            method="GET",
            route="/old",
            status=500,
            message="",
            location=None,
            trace_id=None,
            now=old,
        )
    quiet_client.get("/__test/boom")  # 정리는 저장할 때 한 번씩(시간 간격 제한) 돈다
    assert [e.event_type for e in _events()] == ["ValueError"]


def test_fingerprint_depends_on_every_part():
    base = ("server_error", "ValueError", "/x", 500, "msg")
    assert error_service.make_fingerprint(*base) == error_service.make_fingerprint(*base)
    for i, other in enumerate(("auth_failure", "KeyError", "/y", 503, "other")):
        changed = list(base)
        changed[i] = other
        assert error_service.make_fingerprint(*changed) != error_service.make_fingerprint(*base)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (500, ("server_error", "error")),
        (503, ("server_error", "error")),
        (401, ("auth_failure", "warning")),
        (403, ("auth_failure", "warning")),
        (400, None),
        (404, None),
        (422, None),
        (200, None),
    ],
)
def test_only_server_errors_and_auth_failures_are_classified(status, expected):
    assert error_service.classify(status) == expected
