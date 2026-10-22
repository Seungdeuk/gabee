"""로그인, JWT Access Token, Refresh Token 회전·로그아웃, 레거시 토큰과의 공존."""

import threading
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from app.features.family_group import service
from app.features.family_group.models import RefreshToken, User
from app.shared import tokens
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.helpers import signup

SIGNUP = "/family-group/auth/signup"
LOGIN = "/family-group/auth/login"
REFRESH = "/family-group/auth/refresh"
LOGOUT = "/family-group/auth/logout"
ME = "/family-group/auth/me"
PASSWORD = "Sunny-day-2026"


def register(client, login_id="jimin_kim", email="jimin@example.com", **over):
    body = {"login_id": login_id, "password": PASSWORD, "email": email, "name": "김지민"}
    body.update(over)
    r = client.post(SIGNUP, json=body)
    assert r.status_code == 201, r.text
    return r.json()["user"]


def login(client, login_id="jimin_kim", password=PASSWORD, **extra):
    return client.post(LOGIN, json={"login_id": login_id, "password": password, **extra})


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def refresh_rows(user_id=None):
    with SessionLocal() as db:
        q = select(RefreshToken)
        if user_id:
            q = q.where(RefreshToken.user_id == user_id)
        return list(db.scalars(q))


# ---------- 로그인 ----------
def test_signup_then_login_returns_tokens_and_user(client):
    user = register(client)
    r = login(client, " JIMIN_KIM ", device_label="지민의 폰")  # 아이디는 정규화된다
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == settings.access_token_ttl_seconds
    assert data["refresh_expires_in"] == settings.refresh_token_ttl_seconds
    assert data["user"]["id"] == user["id"] and data["user"]["login_id"] == "jimin_kim"
    assert set(data) == {
        "access_token", "refresh_token", "token_type", "expires_in", "refresh_expires_in", "user",
    }  # fmt: skip
    assert "password" not in r.text and "argon2" not in r.text and "nologin" not in r.text


def test_refresh_token_is_stored_only_as_a_hash(client):
    user = register(client)
    data = login(client, device_label="폰").json()
    (row,) = refresh_rows(user["id"])
    assert row.token_hash == tokens.hash_refresh_token(data["refresh_token"])
    assert data["refresh_token"] not in (row.token_hash, row.id) and len(row.token_hash) == 64
    assert row.device_label == "폰" and row.revoked_at is None
    remaining = (row.expires_at.replace(tzinfo=UTC) - datetime.now(UTC)).total_seconds()
    assert 0 < remaining <= settings.refresh_token_ttl_seconds


def test_wrong_password_and_unknown_user_look_identical(client):
    register(client)
    wrong = login(client, password="Wrong-pass-1")
    unknown = login(client, login_id="nobody_here")
    malformed = login(client, login_id="x")
    for r in (wrong, unknown, malformed):
        assert r.status_code == 401 and r.json() == wrong.json()
    assert wrong.json()["code"] == "invalid_credentials"


def test_accounts_without_a_password_cannot_log_in(client):
    assert signup(client, "익명")  # 익명 계정은 login_id/password_hash 가 없다
    assert login(client, login_id="anonymous1").status_code == 401


def test_login_is_rate_limited_per_login_id(client):
    register(client)
    for _ in range(settings.login_max_failures_per_id):
        assert login(client, password="Wrong-pass-1").status_code == 401
    blocked = login(client)  # 이제는 맞는 비밀번호도 한동안 거부 (무차별 대입 방지)
    assert blocked.status_code == 429 and blocked.json()["code"] == "too_many_attempts"
    assert int(blocked.headers["Retry-After"]) >= 1
    other = login(client, login_id="other_user", password="Wrong-pass-1")
    assert other.status_code == 401  # 다른 아이디는 영향 없음


def test_successful_login_resets_the_failure_count(client):
    register(client)
    for _ in range(settings.login_max_failures_per_id - 1):
        login(client, password="Wrong-pass-1")
    assert login(client).status_code == 200
    for _ in range(settings.login_max_failures_per_id - 1):
        assert login(client, password="Wrong-pass-1").status_code == 401  # 다시 처음부터 센다


# ---------- Bearer 인증 ----------
def test_bearer_authenticates_me_and_existing_apis(client):
    register(client)
    access = login(client).json()["access_token"]
    me = client.get(ME, headers=bearer(access))
    assert me.status_code == 200 and me.json()["login_id"] == "jimin_kim"
    assert set(me.json()) == {
        "id", "name", "role", "active_group_id", "location_consent",
        "login_id", "email", "email_verified",
    }  # fmt: skip
    assert client.get("/family-group/me", headers=bearer(access)).status_code == 200
    group = client.post("/family-group/groups", json={"name": "우리 가족"}, headers=bearer(access))
    assert group.status_code == 201
    for path in ("/family-chat/messages", "/schedule/events", "/billing/expenses", "/care/records"):
        assert client.get(path, headers=bearer(access)).status_code == 200, path


def test_missing_and_malformed_authorization_headers(client):
    assert client.get(ME).json()["code"] == "token_required"
    for value in ("", "Bearer", "Bearer  ", "Basic abc", "Token abc", "Bearer a b", "bearer"):
        r = client.get(ME, headers={"Authorization": value})
        assert r.status_code == 401 and r.json()["code"] == "token_invalid", value
    assert client.get(ME, headers=bearer("not.a.jwt")).json()["code"] == "token_invalid"


def test_expired_access_token_is_rejected_with_a_distinct_code(client):
    user = register(client)
    old = datetime.now(UTC) - timedelta(seconds=settings.access_token_ttl_seconds + 60)
    token, _ = tokens.create_access_token(user["id"], now=old)
    r = client.get(ME, headers=bearer(token))
    assert r.status_code == 401 and r.json()["code"] == "token_expired"


def _forge(claims_over=None, secret=None, algorithm="HS256", drop=()):
    now = datetime.now(UTC)
    claims = {
        "iss": settings.jwt_issuer, "aud": settings.jwt_audience, "sub": "x",
        "iat": now, "exp": now + timedelta(minutes=5), "jti": "j", "token_use": "access",
    }  # fmt: skip
    claims.update(claims_over or {})
    for k in drop:
        claims.pop(k)
    return jwt.encode(claims, secret or settings.jwt_secret, algorithm=algorithm)


def test_forged_and_wrongly_scoped_jwts_are_rejected(client):
    uid = register(client)["id"]
    future = datetime.now(UTC) + timedelta(hours=1)
    cases = {
        "다른 비밀키로 서명": _forge({"sub": uid}, secret="another-secret-another-secret-another-secret"),
        "issuer 다름": _forge({"sub": uid, "iss": "evil"}),
        "audience 다름": _forge({"sub": uid, "aud": "other-app"}),
        "refresh 용도 토큰": _forge({"sub": uid, "token_use": "refresh"}),
        "용도 클레임 없음": _forge({"sub": uid}, drop=("token_use",)),
        "sub 없음": _forge({}, drop=("sub",)),
        "exp 없음": _forge({"sub": uid}, drop=("exp",)),
        "jti 없음": _forge({"sub": uid}, drop=("jti",)),
        "아직 유효하지 않음(iat 미래)": _forge({"sub": uid, "iat": future}),
        "알고리즘 HS512": _forge({"sub": uid}, algorithm="HS512"),
    }  # fmt: skip
    for name, token in cases.items():
        r = client.get(ME, headers=bearer(token))
        assert r.status_code == 401 and r.json()["code"] == "token_invalid", name
    good = _forge({"sub": uid})  # 대조군: 위 케이스가 거부된 것은 각 결함 때문이다
    assert client.get(ME, headers=bearer(good)).status_code == 200


def test_alg_none_and_tampered_signature_are_rejected(client):
    user = register(client)
    unsigned = jwt.encode({"sub": user["id"]}, key=None, algorithm="none")
    assert client.get(ME, headers=bearer(unsigned)).json()["code"] == "token_invalid"
    token = login(client).json()["access_token"]
    head, payload, sig = token.split(".")
    tampered = ".".join([head, payload, sig[:-2] + ("AA" if not sig.endswith("AA") else "BB")])
    assert client.get(ME, headers=bearer(tampered)).json()["code"] == "token_invalid"


def test_refresh_token_cannot_be_used_as_a_bearer(client):
    register(client)
    refresh = login(client).json()["refresh_token"]
    assert client.get(ME, headers=bearer(refresh)).json()["code"] == "token_invalid"


def test_token_for_a_deleted_user_is_rejected(client):
    user = register(client)
    access = login(client).json()["access_token"]
    with SessionLocal() as db:
        db.query(RefreshToken).delete()
        db.delete(db.get(User, user["id"]))
        db.commit()
    assert client.get(ME, headers=bearer(access)).status_code == 401


def test_role_comes_from_the_database_not_the_token(client):
    user = register(client, role="child")
    forged = _forge(
        {"sub": user["id"], "role": "owner", "scope": "admin"}
    )  # 클레임 주장은 무시된다
    assert client.get(ME, headers=bearer(forged)).json()["role"] == "child"
    owner = signup(client, "주인")  # 다른 가족의 그룹 데이터에는 접근할 수 없다
    client.post("/family-group/groups", json={"name": "남의 가족"}, headers=owner)
    assert client.get("/family-group/groups/me", headers=bearer(forged)).status_code == 404


# ---------- 레거시 토큰과의 공존 ----------
def test_bearer_failure_never_falls_back_to_the_legacy_token(client):
    headers = signup(client, "익명")  # 유효한 레거시 토큰
    r = client.get("/family-group/me", headers={**headers, "Authorization": "Bearer garbage"})
    assert r.status_code == 401 and r.json()["code"] == "token_invalid"
    r = client.get("/family-group/me", headers={**headers, "Authorization": "Basic zzz"})
    assert r.status_code == 401
    expired, _ = tokens.create_access_token("x", now=datetime.now(UTC) - timedelta(days=1))
    r = client.get("/family-group/me", headers={**headers, "Authorization": f"Bearer {expired}"})
    assert r.json()["code"] == "token_expired"


def test_anonymous_accounts_keep_working_with_the_legacy_token(client):
    headers = signup(client, "익명")
    assert client.get("/family-group/me", headers=headers).status_code == 200
    assert (
        client.post("/family-group/groups", json={"name": "가족"}, headers=headers).status_code
        == 201
    )
    assert client.get(ME, headers=headers).status_code == 401  # /auth/me 는 Bearer 전용


def test_credentialed_account_cannot_use_the_legacy_header(client):
    register(client)
    with SessionLocal() as db:
        legacy = db.scalar(select(User.token).where(User.login_id == "jimin_kim"))
    assert legacy.startswith("nologin:")
    r = client.get("/family-group/me", headers={"X-Gyeot-Token": legacy})
    assert r.status_code == 401 and r.json()["code"] == "token_invalid"


def test_legacy_auth_can_be_switched_off_without_affecting_bearer(client, monkeypatch):
    headers = signup(client, "익명")
    register(client)
    access = login(client).json()["access_token"]
    monkeypatch.setattr(settings, "allow_legacy_token_auth", False)
    r = client.get("/family-group/me", headers=headers)
    assert r.status_code == 401 and r.json()["code"] == "legacy_auth_disabled"
    assert client.get("/family-group/me", headers=bearer(access)).status_code == 200


# ---------- Refresh 회전 ----------
def test_refresh_rotates_and_the_old_token_dies(client):
    user = register(client)
    first = login(client, device_label="폰").json()
    r = client.post(REFRESH, json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200, r.text
    second = r.json()
    assert set(second) == {
        "access_token", "refresh_token", "token_type", "expires_in", "refresh_expires_in",
    }  # fmt: skip
    assert second["refresh_token"] != first["refresh_token"]
    assert client.get(ME, headers=bearer(second["access_token"])).status_code == 200
    rows = refresh_rows(user["id"])
    assert len(rows) == 2 and sorted(r.revoked_at is None for r in rows) == [False, True]
    assert {r.device_label for r in rows} == {"폰"}  # 세션 이름이 이어진다

    reuse = client.post(REFRESH, json={"refresh_token": first["refresh_token"]})
    assert reuse.status_code == 401 and reuse.json()["code"] == "refresh_reused"
    assert client.post(REFRESH, json={"refresh_token": second["refresh_token"]}).status_code == 200


def test_reuse_long_after_rotation_revokes_every_session_of_the_user(client):
    user = register(client)
    first = login(client).json()
    other_device = login(client).json()
    second = client.post(REFRESH, json={"refresh_token": first["refresh_token"]}).json()
    with SessionLocal() as db:  # 회전이 오래전에 일어난 것처럼 만든다
        row = db.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == tokens.hash_refresh_token(first["refresh_token"])
            )
        )
        row.revoked_at = datetime.now(UTC) - service._REUSE_GRACE - timedelta(seconds=5)
        db.commit()
    reused = client.post(REFRESH, json={"refresh_token": first["refresh_token"]})
    assert reused.json()["code"] == "refresh_reused"
    assert all(r.revoked_at is not None for r in refresh_rows(user["id"]))  # 탈취로 보고 전부 폐기
    for t in (second, other_device):
        assert client.post(REFRESH, json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_unknown_and_expired_refresh_tokens_are_rejected(client):
    user = register(client)
    assert client.post(REFRESH, json={"refresh_token": "nope"}).json()["code"] == "refresh_invalid"
    data = login(client).json()
    with SessionLocal() as db:
        row = db.scalar(select(RefreshToken).where(RefreshToken.user_id == user["id"]))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    r = client.post(REFRESH, json={"refresh_token": data["refresh_token"]})
    assert r.status_code == 401 and r.json()["code"] == "refresh_invalid"


def test_access_token_is_not_accepted_as_a_refresh_token(client):
    register(client)
    data = login(client).json()
    assert client.post(REFRESH, json={"refresh_token": data["access_token"]}).status_code == 401


def test_concurrent_refresh_with_the_same_token_only_succeeds_once(client):
    register(client)
    token = login(client).json()["refresh_token"]
    results = []
    barrier = threading.Barrier(6)

    def go():
        barrier.wait()
        results.append(client.post(REFRESH, json={"refresh_token": token}).status_code)

    threads = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [200] + [401] * 5, results


# ---------- 로그아웃 ----------
def test_logout_revokes_only_this_session_and_is_idempotent(client):
    user = register(client)
    phone = login(client, device_label="폰").json()
    tablet = login(client, device_label="태블릿").json()
    assert client.post(LOGOUT, json={"refresh_token": phone["refresh_token"]}).status_code == 204
    assert client.post(LOGOUT, json={"refresh_token": phone["refresh_token"]}).status_code == 204
    assert client.post(LOGOUT, json={"refresh_token": "never-issued"}).status_code == 204
    assert client.post(REFRESH, json={"refresh_token": phone["refresh_token"]}).status_code == 401
    assert client.post(REFRESH, json={"refresh_token": tablet["refresh_token"]}).status_code == 200
    assert (
        sum(r.revoked_at is not None for r in refresh_rows(user["id"])) == 2
    )  # 폰 + 회전된 태블릿


def test_logout_needs_a_body_and_returns_no_content(client):
    assert client.post(LOGOUT, json={}).status_code == 422
    r = client.post(LOGOUT, json={"refresh_token": "x"})
    assert r.status_code == 204 and r.content == b""


@pytest.mark.parametrize("path", [LOGIN, REFRESH])
def test_errors_use_the_common_error_shape(client, path):
    body = {"login_id": "nobody_x", "password": "x"} if path == LOGIN else {"refresh_token": "x"}
    r = client.post(path, json=body)
    assert r.status_code == 401 and set(r.json()) == {"code", "message"}
