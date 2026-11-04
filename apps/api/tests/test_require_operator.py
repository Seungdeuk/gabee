"""서비스 운영자 인증(`require_operator`): scope 별 허용 목록, fail-closed, 가족 역할 무관, 레거시 토큰 거부, 동의 검사 순서.

라우터가 아직 없으므로 시험 전용 작은 앱에 보호 경로를 만들어 쓴다. 사용자 id 는 시험에서 만든 가짜 계정의 값이고,
실제 운영 id 는 어디에도 쓰지 않는다. 허용 목록은 요청마다 settings 에서 읽으므로 시험 안에서 값을 바꿔 확인한다.
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.features.family_group.models import User
from app.shared.auth import parse_user_id_list, require_operator
from app.shared.config import Settings, settings
from app.shared.db import SessionLocal
from app.shared.errors import register_error_handlers
from tests.helpers import signup

SIGNUP = "/family-group/auth/signup"
LOGIN = "/family-group/auth/login"
CONSENT = "/family-group/auth/me/tester-consent"
PASSWORD = "Sunny-day-2026"

_app = FastAPI()
register_error_handlers(_app)


@_app.get("/ops")
def _ops(user: User = Depends(require_operator("ops_admin"))) -> dict:
    return {"id": user.id}


@_app.get("/service")
def _service(user: User = Depends(require_operator("service_admin"))) -> dict:
    return {"id": user.id}


@pytest.fixture
def probe():
    return TestClient(_app)


def _member(client, login_id: str) -> tuple[dict, str]:
    """정식 회원을 만들고 (Bearer 헤더, 사용자 id)를 돌려준다."""
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


def _set(monkeypatch, ops: str = "", service: str = "") -> None:
    monkeypatch.setattr(settings, "ops_admin_user_ids", ops)
    monkeypatch.setattr(settings, "service_admin_user_ids", service)


def test_parse_user_id_list():
    assert parse_user_id_list("a, ,b") == {"a", "b"}
    assert parse_user_id_list(" a ,a,,") == {"a"}
    assert parse_user_id_list("") == frozenset()
    assert parse_user_id_list(" , ,") == frozenset()
    assert parse_user_id_list("Ab") != parse_user_id_list("ab")  # 대소문자도 정확히 일치해야 한다


def test_settings_default_is_empty_so_an_unset_list_allows_nobody():
    # 환경변수가 없을 때의 기본값. 비어 있으면 아무도 통과하지 못한다(fail-closed).
    for field in ("ops_admin_user_ids", "service_admin_user_ids"):
        assert Settings.model_fields[field].default == ""


def test_unknown_scope_fails_when_the_dependency_is_created():
    with pytest.raises(ValueError):
        require_operator("ops_admn")


def test_without_token_is_401(probe):
    r = probe.get("/ops")
    assert r.status_code == 401 and r.json()["code"] == "token_required"


def test_empty_or_missing_list_allows_nobody(client, probe, monkeypatch):
    headers, _ = _member(client, "jimin_kim")
    for raw in ("", " , ,"):
        _set(monkeypatch, ops=raw, service=raw)
        for path in ("/ops", "/service"):
            r = probe.get(path, headers=headers)
            assert r.status_code == 403 and r.json()["code"] == "operator_required"


def test_user_outside_the_list_gets_403_without_hints(client, probe, monkeypatch):
    headers, _ = _member(client, "jimin_kim")
    _, other_id = _member(client, "minsu_lee")
    _set(monkeypatch, ops=other_id)
    r = probe.get("/ops", headers=headers)
    assert r.status_code == 403
    assert set(r.json()) == {"code", "message"} and r.json()["code"] == "operator_required"
    assert other_id not in r.text  # 허용 목록의 내용은 응답에 나오지 않는다


def test_listed_user_passes_and_whitespace_is_trimmed(client, probe, monkeypatch):
    headers, user_id = _member(client, "jimin_kim")
    _set(monkeypatch, ops=f" x , {user_id} ,, ")
    r = probe.get("/ops", headers=headers)
    assert r.status_code == 200 and r.json() == {"id": user_id}


def test_family_owner_is_not_an_operator_unless_listed(client, probe, monkeypatch):
    headers, user_id = _member(client, "jimin_kim")
    assert (
        client.post("/family-group/groups", json={"name": "시험 가족"}, headers=headers).status_code
        == 201
    )
    _set(monkeypatch)
    assert (
        probe.get("/ops", headers=headers).status_code == 403
    )  # 가족 owner 여도 목록에 없으면 403
    assert probe.get("/service", headers=headers).status_code == 403
    _set(monkeypatch, ops=user_id)
    assert probe.get("/ops", headers=headers).status_code == 200


def test_scopes_do_not_include_each_other(client, probe, monkeypatch):
    ops_headers, ops_id = _member(client, "jimin_kim")
    svc_headers, svc_id = _member(client, "minsu_lee")
    _set(monkeypatch, ops=ops_id, service=svc_id)
    assert probe.get("/ops", headers=ops_headers).status_code == 200
    assert probe.get("/service", headers=ops_headers).status_code == 403
    assert probe.get("/service", headers=svc_headers).status_code == 200
    assert probe.get("/ops", headers=svc_headers).status_code == 403


def test_legacy_token_is_rejected_even_if_listed(client, probe, monkeypatch):
    legacy = signup(client)
    with SessionLocal() as db:
        legacy_id = db.scalar(select(User.id).where(User.token == legacy["X-Gyeot-Token"]))
    _set(monkeypatch, ops=legacy_id, service=legacy_id)
    for path in ("/ops", "/service"):
        r = probe.get(path, headers=legacy)
        assert r.status_code == 401 and r.json()["code"] == "token_required"


def test_operator_check_comes_before_the_consent_check(client, probe, monkeypatch):
    operator, operator_id = _member(client, "jimin_kim")
    stranger, _ = _member(client, "minsu_lee")
    _set(monkeypatch, ops=operator_id)
    monkeypatch.setattr(settings, "require_tester_consent", True)
    # 운영자가 아니면 동의 여부와 상관없이 같은 403
    r = probe.get("/ops", headers=stranger)
    assert r.status_code == 403 and r.json()["code"] == "operator_required"
    # 운영자도 동의 전에는 막힌다
    r = probe.get("/ops", headers=operator)
    assert r.status_code == 403 and r.json()["code"] == "tester_consent_required"
    # 동의 저장은 열려 있고, 동의 뒤에는 통과한다
    ok = client.put(CONSENT, json={"version": settings.tester_consent_version}, headers=operator)
    assert ok.status_code == 200, ok.text
    assert probe.get("/ops", headers=operator).status_code == 200
