"""채팅방 공유 카드(내 일정 한 건·내 정산 몫): 서버가 직접 읽어 보낸 시점 내용으로 저장하고, 클라이언트 값은 믿지 않는다.
가족 전체방과 1:1 방에서 보낼 수 있고, 지우면 카드 내용도 서버에서 비운다. AI 를 부르지 않는다."""

import copy

import httpx
import pytest
from sqlalchemy import func, select

from app.features.family_chat import chat_push, service
from app.features.family_chat.models import ChatRoom, Message, MessageShare
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
    assert all(not m["share"] for m in _messages(client, a))  # 가족 전체방에는 카드가 없다
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
        status = copy.deepcopy(real(*args, **kwargs))  # 캐시된 상태를 바꾸면 다음 시험이 영향받는다
        status.features["chat_share"] = {"ready": False, "reason": "missing"}
        return status

    monkeypatch.setattr(schema_module.monitor, "status", not_ready)
    assert _share(client, a, "event", event["id"]).status_code == 503


# ---------- 리뷰 반영 ----------

LEAVE_FAMILY = "/family-group/groups/me/leave"


def _drop_share_table():
    from app.shared.db import engine

    MessageShare.__table__.drop(engine)
    return lambda: MessageShare.__table__.create(engine)


def test_leaving_a_direct_room_still_works_when_the_share_table_is_missing(client, trio):  # noqa: F811
    """표(message_shares)가 아직 없는 DB(공용 DB 반영 전)에서도 1:1 방 마지막 나가기가 500 이 되지 않는다."""
    a, b, _ = trio
    room = _direct(client, a, _uid(client, b))
    restore = _drop_share_table()
    try:
        assert client.post(f"/family-chat/rooms/{room['id']}/leave", headers=a).status_code == 204
        assert client.post(f"/family-chat/rooms/{room['id']}/leave", headers=b).status_code == 204
    finally:
        restore()
    with SessionLocal() as db:
        assert db.get(ChatRoom, room["id"]) is None


def test_deleting_a_family_still_works_when_the_share_table_is_missing(client, family):
    from app.features.family_group.models import Group

    a, b, group = family
    _send(client, a, "지워질 글")
    assert client.post(LEAVE_FAMILY, headers=b).status_code in (200, 204)
    restore = _drop_share_table()
    try:
        assert client.post(LEAVE_FAMILY, headers=a).status_code in (200, 204)  # 혼자 남은 소유자
    finally:
        restore()
    with SessionLocal() as db:  # 상태 코드만이 아니라 가족과 메시지가 실제로 지워졌는지 본다
        assert db.get(Group, group["id"]) is None
        assert db.scalar(select(func.count()).select_from(Message)) == 0


def test_deleting_a_family_removes_its_cards(client, family):
    a, b, _ = family
    _share(client, a, "event", _event(client, a)["id"])
    assert _share_rows() == 1
    assert client.post(LEAVE_FAMILY, headers=b).status_code in (200, 204)
    assert client.post(LEAVE_FAMILY, headers=a).status_code in (200, 204)
    assert _share_rows() == 0


def test_the_message_and_its_card_are_saved_together(client, family, monkeypatch):
    """카드 행을 저장하다 실패하면 카드 없는 메시지가 남지 않는다(폴링하는 다른 기기가 빈 카드를 영구히 받지 않게)."""
    from app.features.family_chat import repository as repo

    a, _, _ = family
    event = _event(client, a)

    def boom(*args, **kwargs):
        raise RuntimeError("카드 저장 실패")

    monkeypatch.setattr(repo, "add_share", boom)
    with pytest.raises(RuntimeError):
        _share(client, a, "event", event["id"])
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 0


def test_a_card_cannot_be_sent_to_a_direct_room_whose_peer_left_the_family(client, trio):  # noqa: F811
    a, b, _ = trio
    room = _direct(client, a, _uid(client, b))
    assert client.post(LEAVE_FAMILY, headers=b).status_code in (200, 204)
    r = _share(client, a, "event", _event(client, a)["id"], room["id"])
    assert (
        r.status_code == 409 and r.json()["code"] == "peer_left_room"
    )  # 상대 없이 정산 줄이 풀리지 않는다


def test_old_ownerless_rows_of_someone_else_and_deleted_events_cannot_be_shared(client, family):
    from app.features.schedule.models import Event

    a, b, _ = family
    event = _event(client, a)
    with SessionLocal() as db:  # 주인(user_id)이 없던 옛 줄: 만든 사람이 아니면 못 보낸다
        row = db.get(Event, event["id"])
        row.user_id, row.created_by = None, _uid(client, b)
        db.commit()
    assert _share(client, a, "event", event["id"]).status_code == 404
    mine = _event(client, a)
    assert client.delete(f"/schedule/events/{mine['id']}", headers=a).status_code in (200, 204)
    assert _share(client, a, "event", mine["id"]).status_code == 404  # 지운 일정


def test_a_received_copy_of_a_shared_event_can_be_shared_by_the_receiver(client, family):
    a, b, _ = family
    _event(client, a, share_with=[_uid(client, b)])
    copy_row = client.get("/schedule/events", params={"include_past": True}, headers=b).json()[0]
    r = _share(client, b, "event", copy_row["id"])
    assert r.status_code == 201 and r.json()["share"]["payload"]["title"] == "치과"


# ---------- 최종 리뷰 반영 ----------


def test_direct_card_remaining_is_the_total_of_the_lines_with_that_person(client, trio):  # noqa: F811
    """1:1 카드의 remaining 은 내 전체 잔액이 아니라 그 상대와의 줄 합계라 카드 안에서 앞뒤가 맞는다."""
    a, b, c = trio
    _settled(client, a)
    family = _share(client, a, "settlement", "2026-10").json()["share"]["payload"]
    assert family["remaining"] == 20000  # 가족방 카드는 내 전체 몫
    room = _direct(client, a, _uid(client, c))
    direct = _share(client, a, "settlement", "2026-10", room["id"]).json()["share"]["payload"]
    assert direct["remaining"] == 10000  # 삼촌과의 줄(받을 돈 10000)과 같다
    room_b = _direct(client, b, _uid(client, c))
    payload_b = _share(client, b, "settlement", "2026-10", room_b["id"]).json()["share"]["payload"]
    assert payload_b["remaining"] == 0 and payload_b["lines"] == []  # 삼촌과 주고받을 돈이 없다


def test_share_is_closed_when_the_data_owner_feature_is_not_ready(client, family, monkeypatch):
    """일정·정산 표가 준비되지 않은 DB 에서는 그 기능의 API 처럼 503 이다(컬럼 없음 500 이 아니라)."""
    from app.shared import schema as schema_module

    a, _, _ = family
    event = _event(client, a)
    real = schema_module.monitor.status

    def not_ready(feature):
        def patched(*args, **kwargs):
            status = copy.deepcopy(real(*args, **kwargs))
            status.features[feature] = {"ready": False, "reason": "missing"}
            return status

        return patched

    monkeypatch.setattr(schema_module.monitor, "status", not_ready("schedule"))
    assert _share(client, a, "event", event["id"]).status_code == 503
    monkeypatch.setattr(schema_module.monitor, "status", not_ready("billing"))
    assert _share(client, a, "settlement", "2026-10").status_code == 503


def test_deleting_a_card_removes_its_content_even_when_the_gate_says_not_ready(
    client, family, monkeypatch
):
    """카드 행을 지울지는 캐시된 준비 상태가 아니라 실제 표 유무로 정한다(제목·금액이 서버에 남지 않게)."""
    a, _, _ = family
    card = _share(client, a, "event", _event(client, a)["id"]).json()
    monkeypatch.setattr(service, "share_table_ready", lambda: False)
    assert client.delete(f"{MSG}/{card['id']}", headers=a).status_code == 200
    assert _share_rows() == 0


def test_deleting_a_normal_message_works_when_the_share_table_is_missing(client, family):
    a, _, _ = family
    message_id = _send(client, a, "그냥 글")
    restore = _drop_share_table()
    try:
        assert client.delete(f"{MSG}/{message_id}", headers=a).status_code == 200
    finally:
        restore()
