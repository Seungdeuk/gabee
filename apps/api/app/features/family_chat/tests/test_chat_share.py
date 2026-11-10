"""채팅방 공유 카드(내 일정 한 건·내 정산 몫): 서버가 직접 읽어 보낸 시점 내용으로 저장하고, 클라이언트 값은 믿지 않는다.
가족 전체방과 1:1 방에서 보낼 수 있고, 지우면 카드 내용도 서버에서 비운다. AI 를 부르지 않는다."""

import httpx
import pytest
from sqlalchemy import func, select

from app.features.family_chat import chat_push, service
from app.features.family_chat.models import ChatRoom, MessageShare
from app.shared import chat_share
from app.shared.db import SessionLocal
from app.shared.llm import client as llm

from .test_rooms import _direct, _send, _uid, trio  # noqa: F401  (trio 는 fixture)

SHARES = "/family-chat/shares"
MSG = "/family-chat/messages"


@pytest.fixture(autouse=True)
def _no_ai(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)
    chat_share.limiter.reset()


def _event(client, headers, **extra) -> dict:
    body = {
        "title": "치과",
        "start_date": "2030-01-05",
        "start_time": "10:00:00",
        "end_time": "11:00:00",
        "place": "역삼동 치과",
        "memo": "비밀 메모",
        **extra,
    }
    r = client.post("/schedule/events", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _share(client, headers, kind, ref, room_id=None):
    body = {"kind": kind, "ref": ref}
    if room_id is not None:
        body["room_id"] = room_id
    return client.post(SHARES, json=body, headers=headers)


def _messages(client, headers, room_id=None):
    params = {"latest": True, "limit": 50}
    if room_id:
        params["room_id"] = room_id
    r = client.get(MSG, params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _settled(client, headers, amount=30000):
    """지민(a)이 낸 지출을 '전체' 태그로 정산한다(10월)."""
    e = client.post(
        "/billing/expenses",
        json={"title": "병원비", "amount": amount, "date": "2026-10-12"},
        headers=headers,
    ).json()
    r = client.post(
        "/billing/settlement/tag",
        json={"month": "2026-10", "expense_ids": [e["id"]], "tag": "all"},
        headers=headers,
    )
    assert r.status_code == 200, r.text


# ---------- 일정 카드 ----------


def test_event_card_is_a_message_with_a_server_made_snapshot(client, family):
    a, b, _ = family
    event = _event(client, a)
    r = _share(client, a, "event", event["id"])
    assert r.status_code == 201, r.text
    card = r.json()
    assert (
        card["text"] == "일정을 공유했어요"
    )  # 개인정보 없는 고정 문구(구버전 앱도 말풍선이 보인다)
    assert card["share"]["kind"] == "event"
    payload = card["share"]["payload"]
    assert payload["title"] == "치과" and payload["place"] == "역삼동 치과"
    assert (payload["date"], payload["start_time"], payload["end_time"]) == (
        "2030-01-05",
        "10:00",
        "11:00",
    )
    assert "memo" not in payload and "비밀 메모" not in str(card)  # 메모는 담지 않는다
    # 같은 방의 다른 사람도 목록에서 같은 카드를 본다
    seen = [m for m in _messages(client, b) if m["id"] == card["id"]]
    assert seen and seen[0]["share"]["payload"]["title"] == "치과"


def test_event_card_shows_the_names_of_people_doing_it_together(client, family):
    a, b, _ = family
    event = _event(client, a, share_with=[_uid(client, b)])
    card = _share(client, a, "event", event["id"]).json()
    assert card["share"]["payload"]["with_names"] == ["수진"]


def test_cannot_share_someone_elses_event_or_a_missing_one(client, family, other_family):
    a, b, _ = family
    mine = _event(client, a)
    assert _share(client, b, "event", mine["id"]).status_code == 404  # 같은 가족이어도 남의 줄
    assert _share(client, other_family, "event", mine["id"]).status_code == 404
    assert _share(client, a, "event", "nope").status_code == 404


def test_card_keeps_the_content_from_when_it_was_sent(client, family):
    a, _, _ = family
    event = _event(client, a)
    card = _share(client, a, "event", event["id"]).json()
    client.put(f"/schedule/events/{event['id']}", json={"title": "내과"}, headers=a)
    after = [m for m in _messages(client, a) if m["id"] == card["id"]][0]
    assert after["share"]["payload"]["title"] == "치과"  # 원본을 고쳐도 카드는 그대로


def test_client_cannot_supply_the_card_content(client, family):
    a, _, _ = family
    event = _event(client, a)
    body = {"kind": "event", "ref": event["id"], "payload": {"title": "위조"}}
    assert client.post(SHARES, json=body, headers=a).status_code == 422
    assert _share(client, a, "bogus", event["id"]).status_code == 422


# ---------- 정산 카드(내 몫만) ----------


def test_settlement_card_has_only_my_share(client, trio):  # noqa: F811
    a, b, c = trio
    _settled(client, a)
    card = _share(client, a, "settlement", "2026-10")
    assert card.status_code == 201, card.text
    payload = card.json()["share"]["payload"]
    assert payload["month"] == "2026-10"
    assert payload["remaining"] == 20000  # 30000 을 셋이 나눠 지민은 받을 돈 20000
    assert sorted((x["direction"], x["name"], x["amount"]) for x in payload["lines"]) == [
        ("receive", "삼촌", 10000),
        ("receive", "수진", 10000),
    ]
    # 수진의 카드에는 수진의 몫만(지민에게 보낼 돈), 삼촌 줄은 없다
    mine = _share(client, b, "settlement", "2026-10").json()["share"]["payload"]
    assert mine["remaining"] == -10000
    assert [(x["direction"], x["name"], x["amount"]) for x in mine["lines"]] == [
        ("send", "지민", 10000)
    ]


def test_settlement_card_in_a_direct_room_only_has_lines_with_that_person(client, trio):  # noqa: F811
    a, b, c = trio
    _settled(client, a)
    room = _direct(client, a, _uid(client, c))
    payload = _share(client, a, "settlement", "2026-10", room["id"]).json()["share"]["payload"]
    assert [(x["direction"], x["name"], x["amount"]) for x in payload["lines"]] == [
        ("receive", "삼촌", 10000)
    ]  # 수진과의 줄은 삼촌에게 보이지 않는다


def test_settlement_card_needs_my_involvement_and_a_valid_month(client, family, other_family):
    a, _, _ = family
    assert _share(client, a, "settlement", "2026-10").status_code == 404  # 정산된 내역이 없다
    assert _share(client, a, "settlement", "2026-13").status_code == 400
    _settled(client, a)
    assert _share(client, other_family, "settlement", "2026-10").status_code == 404


# ---------- 방 규칙 ----------


def test_card_can_be_sent_to_a_direct_room_and_only_its_two_people_see_it(client, trio):  # noqa: F811
    a, b, c = trio
    room = _direct(client, a, _uid(client, b))
    event = _event(client, a)
    card = _share(client, a, "event", event["id"], room["id"]).json()
    assert [m["id"] for m in _messages(client, b, room["id"]) if m["share"]] == [card["id"]]
    assert _messages(client, a) == [] or all(not m["share"] for m in _messages(client, a))
    assert _share(client, c, "event", _event(client, c)["id"], room["id"]).status_code == 404


def test_card_cannot_be_sent_after_the_peer_left_the_direct_room(client, trio):  # noqa: F811
    a, b, _ = trio
    room = _direct(client, a, _uid(client, b))
    assert client.post(f"/family-chat/rooms/{room['id']}/leave", headers=b).status_code == 204
    event = _event(client, a)
    r = _share(client, a, "event", event["id"], room["id"])
    assert r.status_code == 409 and r.json()["code"] == "peer_left_room"


def test_card_sends_the_fixed_push_and_counts_as_unread(client, family, monkeypatch):
    a, b, _ = family
    sent = []
    monkeypatch.setattr(
        chat_push, "notify_new_message", lambda db, room, message: sent.append(message.id)
    )
    card = _share(client, a, "event", _event(client, a)["id"]).json()
    assert sent == [card["id"]]
    assert client.get("/family-chat/unread", headers=b).json()["unread"] == 1


def test_card_sending_is_rate_limited(client, family):
    a, _, _ = family
    event = _event(client, a)
    statuses = [_share(client, a, "event", event["id"]).status_code for _ in range(12)]
    assert statuses[:10] == [201] * 10 and statuses[10:] == [429, 429]


def test_card_fails_closed_when_no_provider_is_registered(client, family, monkeypatch):
    a, _, _ = family
    event = _event(client, a)
    monkeypatch.setattr(chat_share, "_providers", {})
    r = _share(client, a, "event", event["id"])
    assert r.status_code == 503  # 카드 내용을 만들 수 없으면 보내지 않는다
    assert _messages(client, a) == []


# ---------- 삭제 ----------


def _share_rows():
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(MessageShare))


def test_deleting_the_card_removes_its_content_from_the_server(client, family):
    a, b, _ = family
    card = _share(client, a, "event", _event(client, a)["id"]).json()
    assert _share_rows() == 1
    assert client.delete(f"{MSG}/{card['id']}", headers=b).status_code == 403  # 보낸 사람만
    r = client.delete(f"{MSG}/{card['id']}", headers=a)
    assert r.status_code == 200 and r.json()["share"] is None and r.json()["deleted"] is True
    assert _share_rows() == 0
    gone = [m for m in _messages(client, b) if m["id"] == card["id"]][0]
    assert gone["share"] is None and gone["text"] == ""


def test_both_people_leaving_a_direct_room_purges_the_cards(client, trio):  # noqa: F811
    a, b, _ = trio
    room = _direct(client, a, _uid(client, b))
    _share(client, a, "event", _event(client, a)["id"], room["id"])
    assert _share_rows() == 1
    assert client.post(f"/family-chat/rooms/{room['id']}/leave", headers=a).status_code == 204
    assert client.post(f"/family-chat/rooms/{room['id']}/leave", headers=b).status_code == 204
    assert _share_rows() == 0
    with SessionLocal() as db:
        assert db.get(ChatRoom, room["id"]) is None


# ---------- 준비 안 된 DB ----------


def test_messages_still_load_when_the_share_table_is_not_ready(client, family, monkeypatch):
    a, _, _ = family
    card = _share(client, a, "event", _event(client, a)["id"]).json()
    monkeypatch.setattr(service, "share_table_ready", lambda: False)
    seen = [m for m in _messages(client, a) if m["id"] == card["id"]][0]
    assert seen["share"] is None and seen["text"] == "일정을 공유했어요"  # 목록은 그대로 열린다


def test_share_api_is_closed_with_503_when_the_table_is_not_ready(client, family, monkeypatch):
    from app.shared import schema as schema_module

    a, _, _ = family
    event = _event(client, a)
    real = schema_module.monitor.status

    def not_ready(*args, **kwargs):
        status = real(*args, **kwargs)
        status.features["chat_share"] = {"ready": False, "reason": "missing"}
        return status

    monkeypatch.setattr(schema_module.monitor, "status", not_ready)
    assert _share(client, a, "event", event["id"]).status_code == 503
