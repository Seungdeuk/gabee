"""채팅 공유 카드(message_shares)를 PostgreSQL 16(최신 Alembic head)에서 검증한다 — 실제 외래키·JSON 컬럼, 메시지 삭제와
1:1 방·가족 삭제 때 카드 내용이 함께 지워지는지.

Docker 가 필요하므로 GABEE_PG16_E2E=1 일 때만 실행한다. 이 시험이 띄운 임시 컨테이너만 쓰며 공용 DB·개인 DB·MVP DB 에는 접속하지 않는다.
"""

import os

import pytest

from tests import test_signup_pg_e2e as _base
from tests.test_join_pg_e2e import PASSWORD, account  # noqa: F401

rows = _base.rows
pg16 = _base.pg16  # 픽스처를 이 모듈에서도 쓰기 위해 이름을 다시 연결한다
pg_client = _base.pg_client

pytestmark = pytest.mark.skipif(
    os.environ.get("GABEE_PG16_E2E") != "1", reason="GABEE_PG16_E2E=1 일 때만 실행(Docker 필요)"
)

P = "/family-group"


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
    return client.get(f"{P}/me", headers=headers).json()["id"]


def _event(client, headers):
    r = client.post(
        "/schedule/events",
        json={"title": "치과", "start_date": "2030-01-05", "start_time": "10:00:00", "memo": "비밀"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_cards_are_stored_deleted_and_purged_on_postgres(pg_client):
    client, pg = pg_client
    owner, guest, _ = _family(client)
    event_id = _event(client, owner)

    # 1) 가족 전체방 카드: 저장되고 JSON 으로 읽힌다
    card = client.post(
        "/family-chat/shares", json={"kind": "event", "ref": event_id}, headers=owner
    )
    assert card.status_code == 201, card.text
    assert card.json()["share"]["payload"]["title"] == "치과"
    ((kind, title, memo_in_payload),) = rows(
        pg,
        "SELECT kind, payload->>'title', payload->>'memo' FROM message_shares",
    )
    assert (kind, title, memo_in_payload) == ("event", "치과", None)  # 메모는 담지 않는다
    seen = client.get("/family-chat/messages", params={"latest": True, "limit": 20}, headers=guest)
    assert seen.json()[-1]["share"]["kind"] == "event"

    # 2) 정산 카드(내 몫): 정산하기까지 마친 지출이 있어야 한다
    expense = client.post(
        "/billing/expenses",
        json={"title": "병원비", "amount": 30000, "date": "2026-10-12"},
        headers=owner,
    ).json()
    r = client.post(
        "/billing/settlement/tag",
        json={"month": "2026-10", "expense_ids": [expense["id"]], "tag": "all"},
        headers=owner,
    )
    assert r.status_code == 200, r.text
    settle = client.post(
        "/family-chat/shares", json={"kind": "settlement", "ref": "2026-10"}, headers=owner
    )
    assert settle.status_code == 201, settle.text
    assert settle.json()["share"]["payload"]["remaining"] == 15000

    # 3) 메시지를 지우면 카드 내용도 지워진다(남의 카드는 못 지움)
    assert client.delete(f"/family-chat/messages/{card.json()['id']}", headers=guest).status_code == 403
    r = client.delete(f"/family-chat/messages/{card.json()['id']}", headers=owner)
    assert r.status_code == 200 and r.json()["share"] is None
    assert rows(pg, "SELECT count(*) FROM message_shares") == [(1,)]

    # 4) 1:1 방 카드는 그 상대와의 줄만 담고, 둘 다 나가면 방과 함께 지워진다
    room = client.post(
        "/family-chat/rooms/direct", json={"user_id": _me(client, guest)}, headers=owner
    ).json()
    direct = client.post(
        "/family-chat/shares",
        json={"kind": "event", "ref": event_id, "room_id": room["id"]},
        headers=owner,
    )
    assert direct.status_code == 201, direct.text
    assert rows(pg, "SELECT count(*) FROM message_shares") == [(2,)]
    assert client.post(f"/family-chat/rooms/{room['id']}/leave", headers=owner).status_code == 204
    assert client.post(f"/family-chat/rooms/{room['id']}/leave", headers=guest).status_code == 204
    assert rows(pg, "SELECT count(*) FROM message_shares WHERE room_id = %s", room["id"]) == [(0,)]
    assert rows(pg, "SELECT count(*) FROM message_shares") == [(1,)]  # 가족방의 정산 카드만 남는다
