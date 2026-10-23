"""Google·Kakao 로그인(PR 4-D)을 PostgreSQL 16(최신 Alembic head)에서 검증한다 — 동시 첫 로그인, 동시 연동 해제(행 잠금), 소셜 계정 중복 제약.

Docker 가 필요하므로 GABEE_PG16_E2E=1 일 때만 실행한다. 임시 컨테이너만 쓰며 공용 DB·개인 DB·MVP DB 에는 접속하지 않는다.
제공자 검증은 가짜로 바꿔 끼운다(실제 Google·Kakao 서버에 접속하지 않는다).
"""

import os
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from app.features.family_group import social_providers as providers
from tests import test_signup_pg_e2e as _base
from tests.test_schema_gate_pg_e2e import admin

rows = _base.rows
pg16 = _base.pg16  # 픽스처를 이 모듈에서도 쓰기 위해 이름을 다시 연결한다
pg_client = _base.pg_client

pytestmark = pytest.mark.skipif(
    os.environ.get("GABEE_PG16_E2E") != "1", reason="GABEE_PG16_E2E=1 일 때만 실행(Docker 필요)"
)

P = "/family-group/auth/social"
TOKEN = "x" * 20


@pytest.fixture(autouse=True)
def _reset():
    yield
    providers._overrides.clear()


def fake(provider, uid, email=None):
    providers.set_verifier(provider, lambda token: providers.Identity(provider, uid, email, "지민"))


def test_simultaneous_first_logins_create_one_user_and_one_account(pg_client):
    client, pg = pg_client
    fake("google", "g-1", "jimin@gmail.com")

    def go(_):
        r = client.post(f"{P}/google", json={"provider_token": TOKEN})
        return r.status_code, r.json().get("user", {}).get("id") or r.json().get(
            "candidate_account"
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(go, range(8)))
    assert all(code == 200 for code, _ in results), results  # 500 이 없어야 한다
    assert rows(pg, "SELECT count(*) FROM users") == [(1,)]
    assert rows(pg, "SELECT count(*) FROM social_accounts") == [(1,)]
    user_ids = {who for _, who in results if who is not True}
    assert len(user_ids) == 1  # 로그인에 성공한 요청은 모두 같은 계정


def test_simultaneous_unlinks_serialize_on_the_user_row(pg_client):
    client, pg = pg_client
    fake("google", "g-1", "solo@gmail.com")
    headers = {
        "Authorization": "Bearer "
        + client.post(f"{P}/google", json={"provider_token": TOKEN}).json()["access_token"]
    }
    fake("kakao", "k-1")
    assert (
        client.post(f"{P}/kakao/link", json={"provider_token": TOKEN}, headers=headers).status_code
        == 204
    )

    def go(provider):
        return client.delete(f"{P}/{provider}", headers=headers).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(pool.map(go, ["google", "kakao"]))
    assert codes == [204, 403], codes  # 하나만 지워지고 나머지는 마지막 로그인 수단 보호로 거부
    assert rows(pg, "SELECT count(*) FROM social_accounts") == [(1,)]


def test_database_rejects_the_same_social_account_twice(pg_client):
    client, pg = pg_client
    fake("google", "g-1")
    assert client.post(f"{P}/google", json={"provider_token": TOKEN}).status_code == 200
    ((user_id,),) = rows(pg, "SELECT user_id FROM social_accounts")
    with admin(pg) as c:
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute(
                "INSERT INTO social_accounts (id, user_id, provider, provider_uid, linked_at) VALUES ('dup1', %s, 'google', 'g-1', now())",
                (user_id,),
            )
