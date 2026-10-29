"""테스트 참여 동의서: 동의한 버전과 시각을 저장하고, 내 정보에 버전을 돌려준다."""

from sqlalchemy import select

from app.features.family_group.models import User
from app.shared.db import SessionLocal

SIGNUP = "/family-group/auth/signup"
LOGIN = "/family-group/auth/login"
ME = "/family-group/auth/me"
CONSENT = "/family-group/auth/me/tester-consent"
PASSWORD = "Sunny-day-2026"


def _login(client) -> tuple[dict, dict]:
    body = {
        "login_id": "jimin_kim",
        "password": PASSWORD,
        "email": "jimin@example.com",
        "name": "김지민",
    }
    assert client.post(SIGNUP, json=body).status_code == 201
    r = client.post(LOGIN, json={"login_id": "jimin_kim", "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]


def test_new_user_has_not_consented(client):
    headers, user = _login(client)
    assert user["tester_consent_version"] is None
    assert client.get(ME, headers=headers).json()["tester_consent_version"] is None


def test_consent_saves_version_and_time(client):
    headers, user = _login(client)
    r = client.put(CONSENT, json={"version": "v0.1"}, headers=headers)
    assert r.status_code == 200 and r.json()["tester_consent_version"] == "v0.1"
    assert client.get(ME, headers=headers).json()["tester_consent_version"] == "v0.1"
    with SessionLocal() as db:
        row = db.scalar(select(User).where(User.id == user["id"]))
        assert row.tester_consent_version == "v0.1" and row.tester_consent_at is not None


def test_new_version_replaces_old_one(client):
    headers, _ = _login(client)
    client.put(CONSENT, json={"version": "v0.1"}, headers=headers)
    r = client.put(CONSENT, json={"version": "v0.2"}, headers=headers)
    assert r.json()["tester_consent_version"] == "v0.2"


def test_consent_needs_login_and_a_version(client):
    assert client.put(CONSENT, json={"version": "v0.1"}).status_code == 401
    headers, _ = _login(client)
    assert client.put(CONSENT, json={"version": ""}, headers=headers).status_code == 422
    assert client.put(CONSENT, json={}, headers=headers).status_code == 422


def test_gate_blocks_api_until_consent_when_enabled(client, monkeypatch):
    from app.shared.config import settings

    headers, _ = _login(client)
    assert client.get("/family-group/me", headers=headers).status_code == 200  # 기본은 꺼짐
    monkeypatch.setattr(settings, "require_tester_consent", True)
    r = client.get("/family-group/me", headers=headers)
    assert r.status_code == 403 and r.json()["code"] == "tester_consent_required"
    assert client.get(ME, headers=headers).status_code == 200  # 내 정보와 동의 저장은 열려 있다
    assert client.put(CONSENT, json={"version": "v0.0"}, headers=headers).status_code == 200
    assert client.get("/family-group/me", headers=headers).status_code == 403  # 예전 버전은 부족
    client.put(CONSENT, json={"version": settings.tester_consent_version}, headers=headers)
    assert client.get("/family-group/me", headers=headers).status_code == 200
