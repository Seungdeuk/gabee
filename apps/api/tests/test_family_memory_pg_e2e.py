"""AI 추억 동의·설정 표 3개(family_memory_settings, member_memory_consents, photo_analysis_exclusions)와 서비스 흐름을
PostgreSQL 16(최신 Alembic head)에서 검증한다 — 서버 기본값, 실제 외래키 CASCADE, 철회·가족 나가기·사진 삭제·가족 삭제 정리.

Docker 가 필요하므로 GABEE_PG16_E2E=1 일 때만 실행한다. 이 시험이 띄운 임시 컨테이너(메모리 768MB·CPU 1개·데이터는 메모리 위 tmpfs)만 쓰며
공용 DB·개인 DB·MVP DB 에는 접속하지 않는다. 일반 시험(SQLite)이 보지 못하는 PostgreSQL 쪽 동작(기본값·CASCADE·부분 실패)을 본다.
"""

import io
import os
import secrets
import time

import psycopg
import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.features.family_memory import service
from app.shared.config import settings
from tests import test_signup_pg_e2e as _base
from tests.test_join_pg_e2e import account
from tests.test_schema_gate_pg_e2e import IMAGE, admin, docker, url

rows = _base.rows
pg_client = _base.pg_client  # 이 모듈의 pg16 픽스처(아래, 자원 제한 포함)를 이름으로 찾아 쓴다

pytestmark = pytest.mark.skipif(
    os.environ.get("GABEE_PG16_E2E") != "1", reason="GABEE_PG16_E2E=1 일 때만 실행(Docker 필요)"
)

P = "/family-group"
M = "/family-memory"


@pytest.fixture(scope="module")
def pg16():
    """다른 PG e2e 시험의 픽스처와 같지만 자원을 제한한다(메모리 768MB, CPU 1개, 데이터는 tmpfs 라 볼륨이 남지 않는다)."""
    name, password = f"gabee-memory-e2e-{secrets.token_hex(3)}", secrets.token_urlsafe(12)
    env = {**os.environ, "POSTGRES_PASSWORD": password}
    docker(
        "run", "-d", "--rm", "--name", name,
        "--memory", "768m", "--cpus", "1",
        "--tmpfs", "/var/lib/postgresql/data:rw,size=256m",
        "-e", "POSTGRES_PASSWORD", "-p", "127.0.0.1::5432", IMAGE,
        env=env,
    )  # fmt: skip
    try:
        for _ in range(60):
            ready = docker(
                "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", check=False
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        time.sleep(2)
        port = int(
            docker("port", name, "5432/tcp").stdout.strip().splitlines()[0].rsplit(":", 1)[1]
        )
        yield {"port": port, "password": password}
    finally:
        docker("rm", "-f", name, check=False)


@pytest.fixture(autouse=True)
def _settings(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "family_memory_enabled", True)


def _family(client):
    owner = account(client, "owner_kim")
    group = client.post(f"{P}/groups", json={"name": "우리 가족"}, headers=owner).json()
    guest = account(client, "guest_lee")
    req = client.post(f"{P}/groups/join", json={"code": group["invite_code"]}, headers=guest).json()
    if req["status"] == "pending":
        r = client.post(f"{P}/groups/join-requests/{req['id']}/approve", headers=owner)
        assert r.status_code == 200, r.text
    return owner, guest, group


def _me(client, headers):
    me = client.get(f"{P}/me", headers=headers).json()
    return me["id"], me["active_group_id"]


def _photo(client, headers):
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(out, format="JPEG")
    r = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["attachment"]["id"], r.json()["id"]


def _count(pg, table):
    return rows(pg, f"SELECT count(*) FROM {table}")[0][0]


def _eligibility(pg, attachment_id):
    engine = create_engine(url(pg))
    try:
        with sessionmaker(bind=engine)() as db:
            return service.check_photo(db, attachment_id)
    finally:
        engine.dispose()


def test_alembic_head_and_server_defaults_on_postgres(pg_client):
    _, pg = pg_client
    from tests.test_schema_gate_pg_e2e import HEAD  # 코드의 head 리비전

    assert rows(pg, "SELECT version_num FROM alembic_version") == [(HEAD,)]
    client, _ = pg_client
    owner, _, group = _family(client)
    _, gid = _me(client, owner)
    # enabled 를 생략하고 넣으면 서버 기본값 false(행이 있어도 기본은 꺼짐)
    with admin(pg) as conn:
        conn.execute(
            "INSERT INTO family_memory_settings (group_id, updated_at) VALUES (%s, now())", (gid,)
        )
    assert rows(pg, "SELECT enabled FROM family_memory_settings WHERE group_id=%s", gid) == [
        (False,)
    ]
    assert group["id"] == gid


def test_consent_flow_withdraw_exclusion_and_eligibility_on_postgres(pg_client):
    client, pg = pg_client
    owner, guest, _ = _family(client)
    guest_id, gid = _me(client, guest)
    attachment_id, _ = _photo(client, guest)

    assert _eligibility(pg, attachment_id).reason == "family_off"
    assert (
        client.put(f"{M}/settings", json={"enabled": True}, headers=guest).status_code == 403
    )  # member
    assert client.put(f"{M}/settings", json={"enabled": True}, headers=owner).status_code == 200
    assert _eligibility(pg, attachment_id).reason == "no_consent"
    assert client.put(f"{M}/consent", json={"consent": True}, headers=guest).status_code == 200
    with admin(
        pg
    ) as conn:  # 업로더가 일반 사진으로 확인한 상태(D-13: 자동 판별은 photo 를 못 만든다)
        conn.execute(
            "UPDATE chat_photo_checks SET status='photo' WHERE attachment_id=%s", (attachment_id,)
        )
    assert _eligibility(pg, attachment_id).eligible is True

    # 사진별 제외: 업로더 본인만. 다른 구성원은 403, 제외하면 자격 없음, 판별 상태는 그대로
    url_ex = f"{M}/photos/{attachment_id}/exclusion"
    assert client.put(url_ex, json={"excluded": True}, headers=owner).status_code == 403
    assert client.put(url_ex, json={"excluded": True}, headers=guest).status_code == 200
    assert _eligibility(pg, attachment_id).reason == "excluded"
    assert rows(
        pg, "SELECT status FROM chat_photo_checks WHERE attachment_id=%s", attachment_id
    ) == [("photo",)]
    assert client.put(url_ex, json={"excluded": False}, headers=guest).status_code == 200

    # 철회는 즉시 효력, 두 번 보내도 같다(withdrawn_at 은 처음 철회한 시각이 유지된다)
    assert (
        client.put(f"{M}/consent/retro", json={"consent": True}, headers=guest).status_code == 200
    )
    assert client.put(f"{M}/consent", json={"consent": False}, headers=guest).status_code == 200
    first = rows(
        pg,
        "SELECT withdrawn_at, retro_consented_at FROM member_memory_consents WHERE user_id=%s",
        guest_id,
    )
    assert client.put(f"{M}/consent", json={"consent": False}, headers=guest).status_code == 200
    assert (
        rows(
            pg,
            "SELECT withdrawn_at, retro_consented_at FROM member_memory_consents WHERE user_id=%s",
            guest_id,
        )
        == first
    )
    assert first[0][0] is not None and first[0][1] is None  # 소급 동의도 함께 끝남
    assert _eligibility(pg, attachment_id).reason == "no_consent"
    assert _count(pg, "ai_group_settings") == 0  # 대화 분석 동의 표를 건드리지 않는다
    assert gid


def test_photo_delete_removes_exclusion_and_attachment_cascade_on_postgres(pg_client):
    client, pg = pg_client
    _, guest, _ = _family(client)
    attachment_id, message_id = _photo(client, guest)
    assert (
        client.put(
            f"{M}/photos/{attachment_id}/exclusion", json={"excluded": True}, headers=guest
        ).status_code
        == 200
    )
    assert _count(pg, "photo_analysis_exclusions") == 1
    assert client.delete(f"/family-chat/messages/{message_id}", headers=guest).status_code == 200
    assert _count(pg, "photo_analysis_exclusions") == 0

    # 훅과 별개로 DB 가 첨부 삭제를 따라간다(ON DELETE CASCADE)
    other_id, _ = _photo(client, guest)
    client.put(f"{M}/photos/{other_id}/exclusion", json={"excluded": True}, headers=guest)
    assert _count(pg, "photo_analysis_exclusions") == 1
    with admin(pg) as conn:
        conn.execute("DELETE FROM message_attachments WHERE id=%s", (other_id,))
    assert _count(pg, "photo_analysis_exclusions") == 0


def test_leaving_family_withdraws_consent_and_purge_deletes_all_rows_on_postgres(pg_client):
    client, pg = pg_client
    owner, guest, _ = _family(client)
    guest_id, gid = _me(client, guest)
    owner_id, _ = _me(client, owner)
    attachment_id, _ = _photo(client, guest)
    client.put(f"{M}/settings", json={"enabled": True}, headers=owner)
    client.put(f"{M}/consent", json={"consent": True}, headers=guest)
    client.put(f"{M}/consent", json={"consent": True}, headers=owner)
    client.put(f"{M}/photos/{attachment_id}/exclusion", json={"excluded": True}, headers=guest)

    assert client.post(f"{P}/groups/me/leave", headers=guest).status_code == 204
    assert rows(
        pg, "SELECT withdrawn_at IS NOT NULL FROM member_memory_consents WHERE user_id=%s", guest_id
    ) == [(True,)]
    assert rows(
        pg, "SELECT withdrawn_at IS NULL FROM member_memory_consents WHERE user_id=%s", owner_id
    ) == [(True,)]

    # 혼자 남은 소유자가 나가면 가족과 함께 세 표의 행이 모두 지워진다(group_purge)
    assert client.post(f"{P}/groups/me/leave", headers=owner).status_code == 204
    for table in ("family_memory_settings", "member_memory_consents", "photo_analysis_exclusions"):
        assert _count(pg, table) == 0, table
    assert rows(pg, "SELECT count(*) FROM groups WHERE id=%s", gid) == [(0,)]


def test_failed_cleanup_rolls_back_withdrawal_on_postgres(pg_client):
    from app.shared import memory_hooks

    client, pg = pg_client
    owner, guest, _ = _family(client)
    guest_id, _ = _me(client, guest)
    client.put(f"{M}/settings", json={"enabled": True}, headers=owner)
    client.put(f"{M}/consent", json={"consent": True}, headers=guest)

    def boom(db, group_id, user_id):
        raise RuntimeError("cleanup failed")

    saved = list(memory_hooks._member_withdrawn)
    memory_hooks.register_member_withdrawn(boom)
    try:
        with pytest.raises(RuntimeError):
            client.put(f"{M}/consent", json={"consent": False}, headers=guest)
        with pytest.raises(RuntimeError):  # 가족 나가기도 통째로 취소된다
            client.post(f"{P}/groups/me/leave", headers=guest)
    finally:
        memory_hooks._member_withdrawn[:] = saved
    assert rows(
        pg, "SELECT withdrawn_at IS NULL FROM member_memory_consents WHERE user_id=%s", guest_id
    ) == [(True,)]
    assert rows(pg, "SELECT count(*) FROM group_members WHERE user_id=%s", guest_id) == [(1,)]


def test_table_constraints_on_postgres(pg_client):
    _, pg = pg_client
    assert psycopg  # 제약 위반은 psycopg 예외로 확인한다
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with admin(pg) as conn:
            conn.execute(
                "INSERT INTO member_memory_consents (group_id, user_id, consent_version)"
                " VALUES ('nope', 'nope', 1)"
            )
