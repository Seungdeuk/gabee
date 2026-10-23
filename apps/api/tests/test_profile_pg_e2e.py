"""가족 프로필·별명·관리자 지정(PR 4-C)을 PostgreSQL 16(최신 Alembic head)에서 검증한다 — 별명의 복합 FK, owner 1명 제약, 동시 권한 변경.

Docker 가 필요하므로 GABEE_PG16_E2E=1 일 때만 실행한다. 임시 컨테이너만 쓰며 공용 DB·개인 DB·MVP DB 에는 접속하지 않는다.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from tests import test_signup_pg_e2e as _base
from tests.test_schema_gate_pg_e2e import admin

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
    return {"Authorization": f"Bearer {token}"}, r.json()["user"]["id"]


def family(client):
    owner, owner_id = account(client, "owner_kim")
    group = client.post(f"{P}/groups", json={"name": "우리 가족"}, headers=owner).json()
    guest, guest_id = account(client, "guest_lee")
    req = client.post(f"{P}/groups/join", json={"code": group["invite_code"]}, headers=guest).json()
    assert (
        client.post(f"{P}/groups/join-requests/{req['id']}/approve", headers=owner).status_code
        == 200
    )
    return owner, owner_id, guest, guest_id, group


def test_roles_profile_and_nickname_on_postgres(pg_client):
    client, pg = pg_client
    owner, owner_id, guest, guest_id, group = family(client)
    assert (
        client.put(
            f"{P}/groups/me/profile",
            json={"display_name": "지민", "family_relation": "daughter"},
            headers=guest,
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"{P}/groups/members/{guest_id}/role", json={"role": "admin"}, headers=owner
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"{P}/groups/me/nicknames/{owner_id}",
            json={"nickname": "엄마", "memo": "메모"},
            headers=guest,
        ).status_code
        == 200
    )
    assert rows(
        pg,
        "SELECT display_name, family_relation, role FROM group_members WHERE user_id = %s",
        guest_id,
    ) == [("지민", "daughter", "admin")]
    assert rows(pg, "SELECT nickname, memo FROM member_nicknames") == [("엄마", "메모")]


def test_database_itself_rejects_nicknames_for_non_members_and_a_second_owner(pg_client):
    client, pg = pg_client
    owner, owner_id, guest, guest_id, group = family(client)
    outsider, outsider_id = account(client, "outsider_x")  # 어느 그룹의 구성원도 아니다
    with admin(pg) as c:
        with pytest.raises(
            psycopg.errors.ForeignKeyViolation
        ):  # 서비스를 거치지 않아도 복합 FK 가 막는다
            c.execute(
                "INSERT INTO member_nicknames (group_id, owner_user_id, target_user_id, updated_at) VALUES (%s, %s, %s, now())",
                (group["id"], owner_id, outsider_id),
            )
    with admin(pg) as c:
        with pytest.raises(psycopg.errors.UniqueViolation):  # 그룹당 owner 는 1명
            c.execute(
                "UPDATE group_members SET role = 'owner' WHERE group_id = %s AND user_id = %s",
                (group["id"], guest_id),
            )
    assert rows(pg, "SELECT count(*) FROM group_members WHERE role = 'owner'") == [(1,)]


def test_simultaneous_role_changes_keep_one_owner_on_postgres(pg_client):
    client, pg = pg_client
    owner, owner_id, guest, guest_id, group = family(client)

    def go(i):
        role = "admin" if i % 2 == 0 else "member"
        return client.put(
            f"{P}/groups/members/{guest_id}/role", json={"role": role}, headers=owner
        ).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert set(pool.map(go, range(8))) == {200}
    assert rows(pg, "SELECT count(*) FROM group_members WHERE role = 'owner'") == [(1,)]
    assert rows(pg, "SELECT role FROM group_members WHERE user_id = %s", owner_id) == [("owner",)]
