"""로그인·Refresh 회전을 PostgreSQL 16(최신 Alembic head)에서 검증한다 — 특히 동시 갱신.

Docker 가 필요하므로 GABEE_PG16_E2E=1 일 때만 실행한다. 임시 컨테이너만 쓰며 공용 DB·개인 DB·MVP DB 에는
접속하지 않는다. 컨테이너/클라이언트 픽스처는 test_signup_pg_e2e 것을 재사용한다.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests import test_signup_pg_e2e as _base

rows = _base.rows
pg16 = _base.pg16  # 픽스처를 이 모듈에서도 쓰기 위해 이름을 다시 연결한다
pg_client = _base.pg_client

pytestmark = pytest.mark.skipif(
    os.environ.get("GABEE_PG16_E2E") != "1", reason="GABEE_PG16_E2E=1 일 때만 실행(Docker 필요)"
)

SIGNUP, LOGIN, REFRESH, LOGOUT, ME = (
    "/family-group/auth/signup",
    "/family-group/auth/login",
    "/family-group/auth/refresh",
    "/family-group/auth/logout",
    "/family-group/auth/me",
)
PASSWORD = "Sunny-day-2026"


def session(client):
    r = client.post(
        SIGNUP,
        json={
            "login_id": "jimin_kim",
            "password": PASSWORD,
            "email": "j@example.com",
            "name": "지민",
        },
    )
    assert r.status_code == 201, r.text
    r = client.post(
        LOGIN, json={"login_id": "jimin_kim", "password": PASSWORD, "device_label": "폰"}
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_signup_login_me_and_existing_api_on_postgres(pg_client):
    client, pg = pg_client
    data = session(client)
    auth = {"Authorization": f"Bearer {data['access_token']}"}
    assert client.get(ME, headers=auth).json()["login_id"] == "jimin_kim"
    assert (
        client.post("/family-group/groups", json={"name": "가족"}, headers=auth).status_code == 201
    )
    assert client.get("/schedule/events", headers=auth).status_code == 200
    ((token_hash, device, revoked),) = rows(
        pg, "SELECT token_hash, device_label, revoked_at FROM refresh_tokens"
    )
    assert len(token_hash) == 64 and token_hash != data["refresh_token"]
    assert (device, revoked) == ("폰", None)


def test_wrong_password_and_legacy_token_on_postgres(pg_client):
    client, pg = pg_client
    session(client)
    bad = client.post(LOGIN, json={"login_id": "jimin_kim", "password": "Wrong-pass-1"})
    assert bad.status_code == 401 and bad.json()["code"] == "invalid_credentials"
    ((legacy,),) = rows(pg, "SELECT token FROM users")
    assert client.get("/family-group/me", headers={"X-Gyeot-Token": legacy}).status_code == 401


def test_eight_simultaneous_refreshes_of_one_token_only_one_wins(pg_client):
    client, pg = pg_client
    data = session(client)

    def go(_):
        return client.post(REFRESH, json={"refresh_token": data["refresh_token"]})

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(go, range(8)))
    codes = sorted(r.status_code for r in responses)
    assert codes == [200] + [401] * 7, codes  # 500(교착·무결성 오류)이 없어야 한다
    winner = next(r for r in responses if r.status_code == 200).json()
    assert {r.json()["code"] for r in responses if r.status_code == 401} == {"refresh_reused"}

    # 폐기 1개 + 새 토큰 1개만 생겼다(경쟁에서 진 요청은 토큰을 만들지 않았다), 승자의 새 토큰은 살아 있다
    assert rows(pg, "SELECT count(*), count(revoked_at) FROM refresh_tokens") == [(2, 1)]
    assert client.post(REFRESH, json={"refresh_token": winner["refresh_token"]}).status_code == 200


def test_logout_and_reuse_on_postgres(pg_client):
    client, pg = pg_client
    data = session(client)
    assert client.post(LOGOUT, json={"refresh_token": data["refresh_token"]}).status_code == 204
    assert client.post(LOGOUT, json={"refresh_token": data["refresh_token"]}).status_code == 204
    assert client.post(REFRESH, json={"refresh_token": data["refresh_token"]}).status_code == 401
    assert rows(pg, "SELECT count(*), count(revoked_at) FROM refresh_tokens") == [(1, 1)]


def test_simultaneous_logins_create_independent_sessions(pg_client):
    client, pg = pg_client
    session(client)

    def go(_):
        return client.post(LOGIN, json={"login_id": "jimin_kim", "password": PASSWORD}).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert set(pool.map(go, range(6))) == {200}
    assert rows(pg, "SELECT count(*) FROM refresh_tokens") == [(7,)]
