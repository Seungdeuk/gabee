"""회원가입을 PostgreSQL 16(최신 Alembic head)에서 검증한다 — 동시 가입 시 unique 제약, 실제 컬럼 타입.

Docker 가 필요하므로 GABEE_PG16_E2E=1 일 때만 실행한다. 이 테스트가 띄운 임시 컨테이너만 쓰며
공용 DB·개인 DB·MVP DB 에는 접속하지 않는다. 컨테이너 기동 헬퍼는 test_schema_gate_pg_e2e 것을 재사용한다.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.shared.db import get_db
from tests.test_schema_gate_pg_e2e import admin, create_db, migrate, pg16, url  # noqa: F401

pytestmark = pytest.mark.skipif(
    os.environ.get("GABEE_PG16_E2E") != "1", reason="GABEE_PG16_E2E=1 일 때만 실행(Docker 필요)"
)

URL = "/family-group/auth/signup"


def payload(n: int = 0, **over):
    data = {
        "login_id": f"user_{n:03d}",
        "password": "Sunny-day-2026",
        "email": f"user{n}@example.com",
        "name": "김지민",
    }
    data.update(over)
    return data


@pytest.fixture
def pg_client(pg16):  # noqa: F811
    create_db(pg16)
    migrate(pg16, "head")  # 최신 head 로 구성
    engine = create_engine(url(pg16), pool_size=12)
    factory = sessionmaker(bind=engine)

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            yield client, pg16
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def rows(pg, sql, *args):
    with admin(pg) as c:
        return c.execute(sql, args).fetchall()


def test_signup_is_stored_in_postgres_with_argon2id(pg_client):
    client, pg = pg_client
    r = client.post(URL, json=payload(1))
    assert r.status_code == 201, r.text
    ((login_id, email, hash_, verified, token, active),) = rows(
        pg,
        "SELECT login_id, email, password_hash, email_verified_at, token, active_group_id FROM users",
    )
    assert (login_id, email, verified, active) == ("user_001", "user1@example.com", None, None)
    assert hash_.startswith("$argon2id$") and token.startswith("nologin:")
    # 레거시 토큰으로는 들어올 수 없다
    assert client.get("/family-group/me", headers={"X-Gyeot-Token": token}).status_code == 401


def test_duplicates_are_409_in_postgres(pg_client):
    client, pg = pg_client
    assert client.post(URL, json=payload(1)).status_code == 201
    assert client.post(URL, json=payload(2, login_id="USER_001")).json()["code"] == "login_id_taken"
    assert (
        client.post(URL, json=payload(3, email="USER1@example.com")).json()["code"] == "email_taken"
    )
    assert rows(pg, "SELECT count(*) FROM users") == [(1,)]


def test_simultaneous_signups_with_same_login_id_create_exactly_one_user(pg_client):
    client, pg = pg_client

    def go(i):
        return client.post(URL, json=payload(i, login_id="same_login")).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(go, range(8)))
    assert sorted(codes) == [201] + [409] * 7, codes  # 500 이 하나도 없어야 한다
    assert rows(pg, "SELECT count(*) FROM users WHERE login_id = 'same_login'") == [(1,)]


def test_simultaneous_signups_with_same_email_create_exactly_one_user(pg_client):
    client, pg = pg_client

    def go(i):
        return client.post(URL, json=payload(i, email="same@example.com")).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(go, range(8)))
    assert sorted(codes) == [201] + [409] * 7, codes
    assert rows(pg, "SELECT count(*) FROM users WHERE email = 'same@example.com'") == [(1,)]
