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


def manual_approval(client, owner):
    """가족의 자동 승인(기본 켜짐, #144)을 끄고 관리자가 승인하는 흐름을 쓴다."""
    r = client.put(f"{P}/groups/invites/settings", json={"auto_approve": False}, headers=owner)
    assert r.status_code == 200, r.text


def test_full_flow_and_simultaneous_decisions_on_postgres(pg_client):
    client, pg = pg_client
    owner = account(client, "owner_kim")
    group = client.post(f"{P}/groups", json={"name": "우리 가족"}, headers=owner).json()
    manual_approval(client, owner)
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
    monkeypatch.setattr(
        settings, "invite_max_uses", 1
    )  # 기본은 20회(가족 단톡방 공유용)라 1회용으로 만든다
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
    assert rows(pg, "SELECT count(*) FROM group_members") == [
        (2,)
    ]  # 자동 승인이라 한 명만 구성원이 됐다


def test_same_user_double_submit_keeps_a_single_pending_request(pg_client, monkeypatch):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "invite_max_uses", 10)
    client, pg = pg_client
    owner = account(client, "owner_kim")
    group = client.post(f"{P}/groups", json={"name": "우리 가족"}, headers=owner).json()
    manual_approval(client, owner)  # 대기 요청(부분 유니크 인덱스)을 보는 시험이라 자동 승인을 끈다
    guest = account(client, "guest_lee")

    def join(_):
        return client.post(f"{P}/groups/join", json={"code": group["invite_code"]}, headers=guest)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(join, range(8)))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert len({r.json()["id"] for r in results}) == 1  # 전부 같은 요청
    assert rows(pg, "SELECT count(*) FROM join_requests WHERE status = 'pending'") == [(1,)]
    assert rows(pg, "SELECT use_count FROM invites") == [(1,)]  # 사용 횟수는 한 번만


def test_auto_approve_same_user_double_submit_never_returns_500(pg_client, monkeypatch):
    """기본값(자동 승인)에서 같은 사람이 동시에 여러 번 제출해도 500 이 나지 않는다: 한 번은 가입되고 나머지는 이미 구성원(409)이다."""
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
    codes = sorted(r.status_code for r in results)
    assert 500 not in codes, [r.text for r in results if r.status_code == 500]
    assert codes.count(200) == 1 and set(codes) <= {200, 409}, codes
    assert all(r.json().get("code") == "already_member" for r in results if r.status_code == 409)
    assert rows(pg, "SELECT count(*) FROM group_members") == [(2,)]  # 소유자 + 게스트, 중복 행 없음
    assert rows(pg, "SELECT count(*), min(status) FROM join_requests") == [(1, "approved")]
    assert rows(pg, "SELECT use_count FROM invites") == [
        (1,)
    ]  # 실패한 시도의 사용 횟수는 되돌아간다


def test_auto_approve_many_different_users_all_join_once(pg_client, monkeypatch):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "invite_max_uses", 10)
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
    assert codes == [200] * 8, codes
    assert rows(pg, "SELECT count(*) FROM group_members") == [(9,)]
    assert rows(pg, "SELECT use_count FROM invites") == [(8,)]
