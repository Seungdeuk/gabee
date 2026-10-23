"""이메일 인증·비밀번호 재설정을 PostgreSQL 16(최신 Alembic head)에서 검증한다 — 동시 토큰 소비, DB 에 해시만 저장.

Docker 가 필요하므로 GABEE_PG16_E2E=1 일 때만 실행한다. 임시 컨테이너만 쓰며 공용 DB·개인 DB·MVP DB 에는
접속하지 않는다. 메일은 보내지 않고 가짜 발송기로 가로챈다.
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.shared import mailer
from tests import test_signup_pg_e2e as _base

rows = _base.rows
pg16 = _base.pg16  # 픽스처를 이 모듈에서도 쓰기 위해 이름을 다시 연결한다
pg_client = _base.pg_client

pytestmark = pytest.mark.skipif(
    os.environ.get("GABEE_PG16_E2E") != "1", reason="GABEE_PG16_E2E=1 일 때만 실행(Docker 필요)"
)

P = "/family-group/auth"
PASSWORD = "Sunny-day-2026"


class Outbox:
    def __init__(self):
        self.mails = []

    def send(self, mail):
        self.mails.append(mail)

    def token(self):
        return re.search(r"token=([\w-]+)", self.mails[-1].body).group(1)


@pytest.fixture
def outbox():
    box = Outbox()
    mailer.set_mailer(box)
    yield box
    mailer.set_mailer(None)


def register_and_login(client):
    r = client.post(
        f"{P}/signup",
        json={
            "login_id": "jimin_kim",
            "password": PASSWORD,
            "email": "j@example.com",
            "name": "지민",
        },
    )
    assert r.status_code == 201, r.text
    return client.post(f"{P}/login", json={"login_id": "jimin_kim", "password": PASSWORD}).json()


def test_verification_on_postgres_stores_only_the_hash_and_unlocks_family_creation(
    pg_client, outbox
):
    client, pg = pg_client
    session = register_and_login(client)
    auth = {"Authorization": f"Bearer {session['access_token']}"}
    assert (
        client.post("/family-group/groups", json={"name": "가족"}, headers=auth).status_code == 403
    )
    assert client.post(f"{P}/email/verify/request", headers=auth).status_code == 204
    token = outbox.token()
    ((token_hash, email, verified),) = rows(
        pg, "SELECT token_hash, email, verified_at FROM email_verifications"
    )
    assert len(token_hash) == 64 and token_hash != token and token not in token_hash
    assert (email, verified) == ("j@example.com", None)
    assert client.post(f"{P}/email/verify/confirm", json={"token": token}).status_code == 200
    assert rows(pg, "SELECT email_verified_at IS NOT NULL FROM users") == [(True,)]
    assert (
        client.post("/family-group/groups", json={"name": "가족"}, headers=auth).status_code == 201
    )


def test_eight_simultaneous_verifications_of_one_token_only_one_wins(pg_client, outbox):
    client, pg = pg_client
    session = register_and_login(client)
    client.post(
        f"{P}/email/verify/request", headers={"Authorization": f"Bearer {session['access_token']}"}
    )
    token = outbox.token()

    def go(_):
        return client.post(f"{P}/email/verify/confirm", json={"token": token}).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = sorted(pool.map(go, range(8)))
    assert codes == [200] + [400] * 7, codes  # 500 이 없어야 한다
    assert rows(pg, "SELECT count(*) FROM email_verifications WHERE verified_at IS NOT NULL") == [
        (1,)
    ]


def test_reset_on_postgres_rotates_password_and_revokes_all_sessions(pg_client, outbox):
    client, pg = pg_client
    session = register_and_login(client)
    other = client.post(f"{P}/login", json={"login_id": "jimin_kim", "password": PASSWORD}).json()
    assert (
        client.post(f"{P}/password/reset/request", json={"email": "j@example.com"}).status_code
        == 204
    )
    assert (
        client.post(f"{P}/password/reset/request", json={"email": "ghost@example.com"}).status_code
        == 204
    )
    assert len(outbox.mails) == 1  # 백그라운드 발송이 끝난 뒤(테스트 클라이언트는 응답 전에 실행)
    ((token_hash, used),) = rows(pg, "SELECT token_hash, used_at FROM password_resets")
    assert len(token_hash) == 64 and used is None and token_hash != outbox.token()

    new = "Brand-new-pass-77"
    r = client.post(
        f"{P}/password/reset/confirm", json={"token": outbox.token(), "new_password": new}
    )
    assert r.status_code == 204
    assert (
        client.post(f"{P}/login", json={"login_id": "jimin_kim", "password": PASSWORD}).status_code
        == 401
    )
    assert (
        client.post(f"{P}/login", json={"login_id": "jimin_kim", "password": new}).status_code
        == 200
    )
    for s in (session, other):
        assert (
            client.post(f"{P}/refresh", json={"refresh_token": s["refresh_token"]}).status_code
            == 401
        )
    assert rows(pg, "SELECT left(password_hash, 10) = '$argon2id$' FROM users") == [(True,)]
    assert (
        rows(pg, "SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL")[0][0] == 1
    )  # 방금 새로 로그인한 세션만


def test_eight_simultaneous_resets_of_one_token_only_one_wins(pg_client, outbox):
    client, pg = pg_client
    session = register_and_login(client)
    client.post(f"{P}/password/reset/request", json={"email": "j@example.com"})
    token = outbox.token()

    def go(i):
        body = {"token": token, "new_password": f"Brand-new-pass-{i}0"}
        return client.post(f"{P}/password/reset/confirm", json=body).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = sorted(pool.map(go, range(8)))
    assert codes == [204] + [400] * 7, codes
    assert rows(pg, "SELECT count(*) FROM password_resets WHERE used_at IS NOT NULL") == [(1,)]
    assert (
        client.post(f"{P}/refresh", json={"refresh_token": session["refresh_token"]}).status_code
        == 401
    )
