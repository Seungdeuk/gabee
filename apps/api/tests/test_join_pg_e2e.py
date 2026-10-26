"""가족 초대·가입 승인(PR 4-B)을 PostgreSQL 16(최신 Alembic head)에서 검증한다 — 동시 승인, 1회용 코드 동시 제출, 부분 유니크 인덱스.

Docker 가 필요하므로 GABEE_PG16_E2E=1 일 때만 실행한다. 임시 컨테이너만 쓰며 공용 DB·개인 DB·MVP DB 에는 접속하지 않는다.
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

P = "/family-group"
PASSWORD = "Sunny-day-2026"


def account(client, login_id):
    r = client.post(
        f"{P}/auth/signup",
        json={
            "login_id": login_id,
            "password": PASSWORD,
            "email": f"{login_id}@example.com",
            "name": login_id,
        },
    )
    assert r.status_code == 201, r.text
    token = client.post(
        f"{P}/auth/login", json={"login_id": login_id, "password": PASSWORD}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_full_flow_and_simultaneous_decisions_on_postgres(pg_client):
    client, pg = pg_client
    owner = account(client, "owner_kim")
    group = client.post(f"{P}/groups", json={"name": "우리 가족"}, headers=owner).json()
    guest = account(client, "guest_lee")
    req = client.post(f"{P}/groups/join", json={"code": group["invite_code"]}, headers=guest).json()
    assert req["status"] == "pending"
    assert rows(pg, "SELECT count(*) FROM group_members") == [(1,)]  # 승인 전에는 구성원이 아니다

    def approve(_):
        return client.post(
            f"{P}/groups/join-requests/{req['id']}/approve", headers=owner
        ).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = sorted(pool.map(approve, range(8)))
    assert codes == [200] + [409] * 7, codes  # 500 이 없어야 한다
    assert rows(
        pg, "SELECT role FROM group_members WHERE user_id <> (SELECT owner_id FROM groups)"
    ) == [("member",)]
    assert rows(pg, "SELECT status FROM join_requests") == [("approved",)]


def test_one_use_code_is_consumed_once_under_concurrent_submissions(pg_client, monkeypatch):
    from app.shared.config import settings

    # 이 시험은 한 IP 에서 틀린 제출 7번이 나오도록 만든다 — 시도 제한(15분 5회)에 걸려 429 가 섞이지 않게 한도를 넉넉히 둔다
    monkeypatch.setattr(settings, "invite_max_failures", 100)
    client, pg = pg_client
    owner = account(client, "owner_kim")
    group = client.post(f"{P}/groups", json={"name": "우리 가족"}, headers=owner).json()
    guests = [account(client, f"guest_{i}") for i in range(8)]

    def join(headers):
        return client.post(
            f"{P}/groups/join", json={"code": group["invite_code"]}, headers=headers
        ).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = sorted(pool.map(join, guests))
    assert codes == [200] + [400] * 7, codes
    assert rows(pg, "SELECT use_count, max_uses FROM invites") == [(1, 1)]
    assert rows(pg, "SELECT count(*) FROM join_requests") == [(1,)]


def test_same_user_double_submit_keeps_a_single_pending_request(pg_client, monkeypatch):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "invite_max_uses", 10)
    client, pg = pg_client
    owner = account(client, "owner_kim")
    group = client.post(f"{P}/groups", json={"name": "우리 가족"}, headers=owner).json()
    guest = account(client, "guest_lee")

    def join(_):
        return client.post(f"{P}/groups/join", json={"code": group["invite_code"]}, headers=guest)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(join, range(8)))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert len({r.json()["id"] for r in results}) == 1  # 전부 같은 요청
    assert rows(pg, "SELECT count(*) FROM join_requests WHERE status = 'pending'") == [(1,)]
    assert rows(pg, "SELECT use_count FROM invites") == [(1,)]  # 사용 횟수는 한 번만
