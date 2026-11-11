"""주간 가족 뉴스 표(member_weekly_news)를 PostgreSQL 16(최신 Alembic head)에서 검증한다 — 실제 외래키 CASCADE,
UNIQUE 제약, JSON 컬럼 왕복, 읽기 API.

Docker 가 필요하므로 GABEE_PG16_E2E=1 일 때만 실행한다. 이 시험이 띄운 임시 컨테이너만 쓰며 공용 DB·개인 DB·MVP DB 에는 접속하지 않는다.
"""

import json
import os
import uuid
from datetime import UTC, date, datetime

import psycopg
import pytest

from app.features.weekly_news import router as news_router
from app.main import app
from tests import test_signup_pg_e2e as _base
from tests.test_join_pg_e2e import account

rows = _base.rows
pg16 = _base.pg16  # 픽스처를 이 모듈에서도 쓰기 위해 이름을 다시 연결한다
pg_client = _base.pg_client

pytestmark = pytest.mark.skipif(
    os.environ.get("GABEE_PG16_E2E") != "1", reason="GABEE_PG16_E2E=1 일 때만 실행(Docker 필요)"
)

P = "/family-group"
WEEK = date(2026, 11, 2)
NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
BODY = {
    "title": "이번 주 우리 가족",
    "items": [{"text": "치과에 다녀왔어요", "source_ids": ["e1"]}],
}
SOURCES = [{"id": "e1", "kind": "event", "ref": "ev1", "label": "치과", "date": "2026-11-03"}]


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


def _insert(pg, group_id, user_id, week=WEEK, status="ok"):
    now = datetime.now(UTC)
    with _base.admin(pg) as conn:
        conn.execute(
            "INSERT INTO member_weekly_news (id, group_id, user_id, week_start, status, body,"
            " sources, model, input_tokens, output_tokens, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                uuid.uuid4().hex, group_id, user_id, week, status,
                json.dumps(BODY), json.dumps(SOURCES), "test-model", 10, 5, now, now,
            ),
        )  # fmt: skip


@pytest.fixture
def fixed_now():
    app.dependency_overrides[news_router.current_time] = lambda: NOW
    yield
    app.dependency_overrides.pop(news_router.current_time, None)


def test_news_table_unique_json_and_read_api_on_postgres(pg_client, fixed_now):
    client, pg = pg_client
    owner, guest, _ = _family(client)
    uid, gid = _me(client, owner)
    guest_id, _ = _me(client, guest)

    _insert(pg, gid, uid)
    # JSON 왕복: 실제 json 컬럼에서 내용이 그대로 읽힌다
    ((title, source_label),) = rows(
        pg, "SELECT body->>'title', sources->0->>'label' FROM member_weekly_news"
    )
    assert (title, source_label) == ("이번 주 우리 가족", "치과")

    # 같은 (가족, 구성원, 주) 는 두 번 넣을 수 없고, 다른 구성원·다른 주는 된다
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert(pg, gid, uid)
    _insert(pg, gid, guest_id)
    _insert(pg, gid, uid, week=date(2026, 11, 9), status="pending")
    assert rows(pg, "SELECT count(*) FROM member_weekly_news") == [(3,)]

    # 읽기 API: 본인 저장본만 보인다
    r = client.get("/report/news", params={"week_start": "2026-11-02"}, headers=owner)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready" and r.json()["items"][0]["source_ids"] == ["e1"]
    assert r.json()["sources"][0]["date"] == "2026-11-03"
    r = client.get("/report/news", params={"week_start": "2026-10-26"}, headers=guest)
    assert r.json()["status"] == "not_generated"  # 게스트의 그 주 저장본은 없다


def test_foreign_keys_are_on_delete_cascade_on_postgres(pg_client):
    _, pg = pg_client
    found = rows(
        pg,
        "SELECT confrelid::regclass::text, confdeltype FROM pg_constraint"
        " WHERE conrelid = 'member_weekly_news'::regclass AND contype = 'f' ORDER BY 1",
    )
    assert found == [("groups", "c"), ("users", "c")]  # c = CASCADE


def test_news_rows_go_with_the_user_and_the_family_on_postgres(pg_client):
    client, pg = pg_client
    owner, _, _ = _family(client)
    uid, gid = _me(client, owner)

    # 사용자 삭제: 그 사용자의 뉴스만 함께 지워진다(FK CASCADE). 가족 없이 가입만 한 사람을 쓴다
    r = client.post(
        f"{P}/auth/signup",
        json={
            "login_id": "lonely_park",
            "password": "Sunny-day-2026",
            "email": "lonely_park@example.com",
            "name": "박외톨",
        },
    )
    assert r.status_code == 201, r.text
    ((lonely_id,),) = rows(pg, "SELECT id FROM users WHERE login_id = 'lonely_park'")
    _insert(pg, gid, uid)
    _insert(pg, gid, lonely_id)
    with _base.admin(pg) as conn:
        conn.execute("DELETE FROM users WHERE id = %s", (lonely_id,))
    assert rows(pg, "SELECT user_id FROM member_weekly_news") == [(uid,)]

    # 혼자 남은 소유자가 가족을 나가면 가족 삭제(group_purge)에 뉴스도 포함된다
    other = account(client, "solo_choi")
    solo_group = client.post(f"{P}/groups", json={"name": "혼자 가족"}, headers=other).json()
    solo_id, solo_gid = _me(client, other)
    assert solo_gid == solo_group["id"]
    _insert(pg, solo_gid, solo_id)
    assert rows(pg, "SELECT count(*) FROM member_weekly_news") == [(2,)]
    assert client.post(f"{P}/groups/me/leave", headers=other).status_code == 204
    assert rows(pg, "SELECT count(*) FROM groups WHERE id = %s", solo_gid) == [(0,)]
    # 다른 가족의 뉴스는 남는다
    assert rows(pg, "SELECT group_id FROM member_weekly_news") == [(gid,)]
