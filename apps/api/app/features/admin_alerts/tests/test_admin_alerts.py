"""관리자 알림: 점검 주소(토큰·꺼짐·중복·기준선), 목록·확인 주소(권한·멱등·없는 키), 개인 정보 없음, 규칙 하나의 실패. 가짜 계정·가짜 지표만 쓴다."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.features.admin_alerts import service as alert_service
from app.features.admin_alerts.models import AdminAlertLog
from app.features.ops_admin import repository as ops_repo
from app.features.ops_admin.models import OpsErrorEvent
from app.shared.config import settings
from app.shared.db import SessionLocal

SIGNUP = "/family-group/auth/signup"
LOGIN = "/family-group/auth/login"
PASSWORD = "Sunny-day-2026"
RUN = "/internal/alerts/run"
LIST = "/admin/alerts"
TOKEN = "test-alert-token"
MEMBER_EMAIL = "alert_tester@example.com"


def _member(client, login_id: str) -> tuple[dict, str]:
    body = {"login_id": login_id, "password": PASSWORD, "email": MEMBER_EMAIL, "name": "시험"}
    assert client.post(SIGNUP, json=body).status_code == 201
    r = client.post(LOGIN, json={"login_id": login_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]["id"]


@pytest.fixture(autouse=True)
def _clean_tables(client):  # client 를 먼저 받아 DB 표가 만들어진 뒤에 지운다
    """이전 시험이 남긴 지표·알림을 지운다(60분 구간 합계가 섞이지 않게)."""
    with SessionLocal() as db:
        ops_repo.delete_before(db, datetime.now(UTC) + timedelta(days=1))
        db.execute(delete(AdminAlertLog))
        db.execute(delete(OpsErrorEvent))
        db.commit()
    yield


@pytest.fixture
def operator(client, monkeypatch) -> dict:
    headers, user_id = _member(client, "alert_operator")
    monkeypatch.setattr(settings, "admin_user_ids", user_id)
    return headers


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "admin_alerts_enabled", True)
    monkeypatch.setattr(settings, "admin_alerts_token", TOKEN)


def _seed(total: int, errors: int) -> None:
    """최근 5분 구간에 요청 total 건 중 5xx errors 건을 넣는다."""
    bucket = (datetime.now(UTC) - timedelta(minutes=5)).replace(second=0, microsecond=0)
    rows = [
        (bucket, "GET", "/sample", "2xx", total - errors, 1.0, 1.0),
        (bucket, "GET", "/sample", "5xx", errors, 1.0, 1.0),
    ]
    with SessionLocal() as db:
        ops_repo.upsert_rows(db, [r for r in rows if r[4] > 0])


def _instant(text: str) -> datetime:
    """시간대 표기가 있든 없든 UTC 기준의 같은 순간으로 맞춘다."""
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if (
        parsed.tzinfo is None
    ):  # 저장된 시각은 항상 UTC 다. 표기가 없으면 UTC 로 본다(내 PC 시간대로 읽지 않는다)
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(tzinfo=None)


def _run(client, token=TOKEN) -> dict:
    headers = {"X-Alert-Token": token} if token is not None else {}
    r = client.post(RUN, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ---- 점검 주소: 토큰


def test_run_needs_the_right_token(client, on):
    assert client.post(RUN).status_code == 403
    assert client.post(RUN, headers={"X-Alert-Token": "wrong"}).status_code == 403


def test_run_is_closed_when_no_token_is_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_alerts_enabled", True)
    monkeypatch.setattr(settings, "admin_alerts_token", "")
    assert client.post(RUN, headers={"X-Alert-Token": ""}).status_code == 403


# ---- 점검 주소: 꺼짐·중복·기준선


def test_disabled_setting_does_nothing(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_alerts_enabled", False)
    monkeypatch.setattr(settings, "admin_alerts_token", TOKEN)
    _seed(total=100, errors=50)
    assert _run(client) == {"enabled": False, "checked": 0, "created": 0}
    with SessionLocal() as db:
        assert db.query(AdminAlertLog).count() == 0


def test_critical_rate_creates_one_alert_and_does_not_repeat(client, on, operator):
    _seed(total=100, errors=10)  # 10% → 긴급
    assert _run(client) == {"enabled": True, "checked": 2, "created": 1}  # 규칙 2개를 돌려 1건 생김
    assert _run(client)["created"] == 0  # 같은 시간대에는 두 번 만들지 않는다
    body = client.get(LIST, headers=operator).json()
    assert body["unacked"] == 1
    item = body["items"][0]
    assert item["rule"] == "server_error_rate" and item["severity"] == "긴급"
    assert item["menu"] == "서버 상태" and item["acked_at"] is None
    assert "10.0%" in item["message"] and "요청 100건 중 5xx 10건" in item["message"]


def test_below_minimum_requests_never_alerts(client, on):
    _seed(total=19, errors=19)  # 100% 여도 20건 미만이면 판단하지 않는다
    assert _run(client)["created"] == 0


def test_warn_level_and_just_under_the_line(client, on, operator):
    _seed(total=200, errors=1)  # 0.5% → 기준 미만
    assert _run(client)["created"] == 0
    with SessionLocal() as db:
        ops_repo.delete_before(db, datetime.now(UTC) + timedelta(days=1))
    _seed(total=200, errors=2)  # 1% → 주의
    assert _run(client)["created"] == 1
    item = client.get(LIST, headers=operator).json()["items"][0]
    assert item["severity"] == "주의" and "기준 1%" in item["message"]


def test_one_failing_rule_does_not_stop_the_others(client, on, operator, monkeypatch):
    def broken(db, now):
        raise RuntimeError("시험용 실패")

    monkeypatch.setattr(
        alert_service,
        "all_rules",
        lambda: [("broken", broken), ("server_error_rate", _real_rule())],
    )
    _seed(total=100, errors=10)
    assert _run(client) == {"enabled": True, "checked": 2, "created": 1}


def _real_rule():
    from app.features.ops_admin.alert_rules import server_error_rate

    return server_error_rate


# ---- 목록·확인 주소: 권한·멱등·없는 키


def test_list_and_ack_are_operator_only(client, on):
    headers, _ = _member(client, "not_an_operator")
    assert client.get(LIST, headers=headers).status_code == 403
    assert client.post(f"{LIST}/x/ack", headers=headers).status_code == 403
    assert client.get(LIST).status_code == 401


def test_ack_is_idempotent_and_clears_the_badge(client, on, operator):
    _seed(total=100, errors=10)
    _run(client)
    key = client.get(LIST, headers=operator).json()["items"][0]["key"]
    first = client.post(f"{LIST}/{key}/ack", headers=operator)
    assert first.status_code == 200
    acked = first.json()
    assert acked["acked_at"] is not None
    again = client.post(f"{LIST}/{key}/ack", headers=operator)
    assert again.status_code == 200
    # 같은 순간인지 본다. 시험 DB(SQLite)는 시간대 표기(Z)를 떼고 돌려주므로 표기는 비교하지 않는다
    assert _instant(again.json()["acked_at"]) == _instant(acked["acked_at"])
    body = client.get(LIST, headers=operator).json()
    assert body["unacked"] == 0 and body["items"][0]["acked_at"] is not None


def test_ack_unknown_key_is_404(client, on, operator):
    r = client.post(f"{LIST}/no-such-key/ack", headers=operator)
    assert r.status_code == 404 and r.json()["code"] == "not_found"


# ---- 개인 정보


def test_list_contains_no_personal_data(client, on, operator):
    _seed(total=100, errors=10)
    _run(client)
    text = client.get(LIST, headers=operator).text
    for secret in (MEMBER_EMAIL, "alert_operator", "시험", operator["Authorization"][-10:]):
        assert secret not in text


# ---- 처음 보는 서버 오류


def _seed_error(
    event_type: str,
    route: str,
    *,
    hours_ago: float = 1,
    message: str = "가린 메시지",
    kind: str = "server_error",
    status: int = 500,
    count: int = 1,
) -> None:
    """오류 기록 한 줄(지문)을 hours_ago 시간 전에 처음 본 것으로 넣는다. count 번 더 나면 횟수가 오른다."""
    when = datetime.now(UTC) - timedelta(hours=hours_ago)
    with SessionLocal() as db:
        for _ in range(count):
            ops_repo.upsert_error_event(
                db,
                fingerprint=f"{kind}|{event_type}|{route}|{status}|{message}",
                kind=kind,
                severity="error" if kind == "server_error" else "warning",
                event_type=event_type,
                method="GET",
                route=route,
                status=status,
                message=message,
                location=None,
                trace_id="trace-secret-123",
                now=when,
            )


def test_new_server_error_alerts_once_without_message_or_trace(client, on, operator):
    _seed_error("KeyError", "/notices", message="비밀 메시지", count=3)
    assert _run(client) == {"enabled": True, "checked": 2, "created": 1}
    assert _run(client)["created"] == 0  # 같은 조합은 다시 알리지 않는다
    body = client.get(LIST, headers=operator)
    item = body.json()["items"][0]
    assert item["rule"] == "new_error" and item["severity"] == "주의"
    assert item["message"] == "처음 보는 서버 오류 KeyError · /notices (3회)"
    assert item["menu"] == "서버 상태"
    assert "비밀 메시지" not in body.text and "trace-secret-123" not in body.text


def test_a_pair_seen_before_the_window_is_not_new(client, on):
    # 3일 전에 이미 있던 조합은, 오늘 메시지만 달라진 줄이 생겨도 새 오류가 아니다
    _seed_error("KeyError", "/notices", hours_ago=72, message="예전 메시지")
    _seed_error("KeyError", "/notices", hours_ago=1, message="오늘 메시지")
    assert _run(client)["created"] == 0


def test_same_pair_with_different_messages_is_counted_once(client, on, operator):
    _seed_error("ValueError", "/schedule", message="가린 A")
    _seed_error("ValueError", "/schedule", message="가린 B", count=2)
    assert _run(client)["created"] == 1
    assert client.get(LIST, headers=operator).json()["items"][0]["message"].endswith("(3회)")


def test_auth_failures_are_not_server_errors(client, on):
    _seed_error("token_invalid", "/family-chat/messages", kind="auth_failure", status=401)
    assert _run(client)["created"] == 0


def test_at_most_ten_new_errors_per_check(client, on):
    for i in range(12):
        _seed_error("RuntimeError", f"/route-{i}")
    assert _run(client)["created"] == 10


def test_long_names_fit_the_alert_table(client, on, operator):
    _seed_error("E" * 100, "/" + "r" * 199)
    assert _run(client)["created"] == 1
    item = client.get(LIST, headers=operator).json()["items"][0]
    assert len(item["message"]) <= 200 and len(item["key"]) <= 120
