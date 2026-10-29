"""게시판 목록: 공지로 올린 메시지는 내려가거나 교체돼도 기록이 남고, 전체 본문·상태를 최신순으로 보고, 구성원 누구나 삭제한다."""

import httpx
import pytest
from sqlalchemy import func, select

from app.features.family_chat import pin_service
from app.features.family_chat.models import ChatBoardPost, ChatPinnedMessage
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from tests.helpers import join_family, signup

PINS = "/family-chat/pins"
BOARD = "/family-chat/board"
MSG = "/family-chat/messages"
DIRECT_ROOM = "/family-chat/rooms/direct"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    pin_service.limiter.reset()

    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)
    yield
    pin_service.limiter.reset()


@pytest.fixture
def trio(client, family):
    a, b, group = family
    c = signup(client, "삼촌")
    assert join_family(client, a, group["invite_code"], c).status_code == 200
    return a, b, c


def _uid(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def _send(client, headers, text, room_id=None):
    body = {"text": text} if room_id is None else {"text": text, "room_id": room_id}
    r = client.post(MSG, json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _pin(client, headers, message_id, room_id=None):
    body = {"message_id": message_id}
    if room_id is not None:
        body["room_id"] = room_id
    r = client.post(PINS, json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _board(client, headers, **params):
    r = client.get(BOARD, params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _posts(client, headers, **params):
    return {i["message_id"]: i for i in _board(client, headers, **params)["items"]}


def test_pinned_message_appears_on_board_with_full_text(client, family):
    a, b, _ = family
    long_text = "가" * 500  # 고정 바는 200자까지만 보이지만 게시판에는 전체 본문이 있다
    mid = _send(client, a, long_text)
    _pin(client, b, mid)
    item = _posts(client, a)[mid]
    assert item["text"] == long_text
    assert item["user_name"] == "지민" and item["posted_by_name"] == "수진"
    assert item["is_current"] is True and item["message_deleted"] is False
    assert item["id"] and item["posted_at"] and item["message_created_at"]


def test_post_stays_after_unpin_and_replacement(client, family):
    a, _, _ = family
    first = _send(client, a, "첫 공지")
    _pin(client, a, first)
    assert client.delete(f"{PINS}/{first}", headers=a).status_code == 204  # 내려도
    items = _posts(client, a)
    assert items[first]["is_current"] is False  # 지난 공지로 남는다
    # 3번째를 올려 가장 오래된 공지가 자동으로 내려가도 기록이 남는다
    second, third, fourth = (_send(client, a, f"공지 {i}") for i in (2, 3, 4))
    for mid in (second, third, fourth):
        _pin(client, a, mid)
    items = _posts(client, a)
    assert set(items) == {first, second, third, fourth}
    assert {m for m, i in items.items() if i["is_current"]} == {third, fourth}
    assert items[second]["is_current"] is False


def test_board_is_newest_first(client, family):
    a, _, _ = family
    ids = [_send(client, a, f"공지 {i}") for i in range(4)]
    for mid in ids:
        _pin(client, a, mid)
    assert [i["message_id"] for i in _board(client, a)["items"]] == list(reversed(ids))


def test_repinning_bumps_the_existing_post_without_duplicates(client, family):
    a, b, _ = family
    first = _send(client, a, "다시 올릴 공지")
    second = _send(client, a, "다른 공지")
    _pin(client, a, first)
    _pin(client, a, second)
    client.delete(f"{PINS}/{first}", headers=a)
    _pin(client, b, first)  # 다른 사람이 다시 올림
    items = _board(client, a)["items"]
    assert [i["message_id"] for i in items] == [first, second]  # 최신으로 올라오고 한 줄뿐
    assert items[0]["posted_by_name"] == "수진" and items[0]["is_current"] is True
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ChatBoardPost)) == 2


def test_post_survives_deleting_the_original_message(client, family):
    a, b, _ = family
    mid = _send(client, a, "곧 지울 공지")
    _pin(client, b, mid)
    assert client.delete(f"{MSG}/{mid}", headers=a).status_code == 200
    item = _posts(client, b)[mid]
    assert item["text"] == "곧 지울 공지" and item["message_deleted"] is True


def test_pagination_with_cursor(client, family):
    a, _, _ = family
    ids = [_send(client, a, f"공지 {i}") for i in range(5)]
    for mid in ids:
        _pin(client, a, mid)
    first = _board(client, a, limit=2)
    assert [i["message_id"] for i in first["items"]] == [ids[4], ids[3]]
    assert first["next_before"]
    second = _board(client, a, limit=2, before=first["next_before"])
    assert [i["message_id"] for i in second["items"]] == [ids[2], ids[1]]
    third = _board(client, a, limit=2, before=second["next_before"])
    assert [i["message_id"] for i in third["items"]] == [ids[0]]
    assert third["next_before"] is None


def test_pagination_stays_consistent_when_a_post_is_bumped(client, family):
    a, _, _ = family
    ids = [_send(client, a, f"공지 {i}") for i in range(3)]
    for mid in ids:
        _pin(client, a, mid)
    page = _board(client, a, limit=1)
    assert page["items"][0]["message_id"] == ids[2]
    _pin(client, a, ids[0])  # 맨 아래 공지를 다시 올려 최신으로 올림
    rest = _board(client, a, limit=5, before=page["next_before"])
    assert [i["message_id"] for i in rest["items"]] == [
        ids[1]
    ]  # 다시 올린 공지는 이미 맨 위로 올라가서 커서 뒤에는 남은 지난 공지만 있다


def test_invalid_cursor_and_limit(client, family):
    a, _, _ = family
    r = client.get(BOARD, params={"before": "이상한값"}, headers=a)
    assert r.status_code == 400 and r.json()["code"] == "invalid_cursor"
    assert client.get(BOARD, params={"limit": 0}, headers=a).status_code == 422
    assert client.get(BOARD, params={"limit": 51}, headers=a).status_code == 422


def test_any_member_can_delete_a_post_and_it_leaves_the_pin_bar(client, trio):
    a, b, c = trio
    mid = _send(client, a, "지울 공지")
    _pin(client, a, mid)
    post_id = _posts(client, a)[mid]["id"]
    r = client.delete(f"{BOARD}/{post_id}", headers=c)  # 올리지도 쓰지도 않은 구성원
    assert r.status_code == 204
    assert mid not in _posts(client, a)
    assert (
        client.get(PINS, headers=a).json()["items"] == []
    )  # 현재 공지였으면 고정 바에서도 내려간다
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ChatPinnedMessage)) == 0
    assert client.delete(f"{BOARD}/{post_id}", headers=b).status_code == 404  # 이미 지웠다


def test_deleting_a_past_post_does_not_touch_current_pins(client, family):
    a, _, _ = family
    old = _send(client, a, "지난 공지")
    cur = _send(client, a, "현재 공지")
    _pin(client, a, old)
    client.delete(f"{PINS}/{old}", headers=a)
    _pin(client, a, cur)
    post_id = _posts(client, a)[old]["id"]
    assert client.delete(f"{BOARD}/{post_id}", headers=a).status_code == 204
    assert [i["message_id"] for i in client.get(PINS, headers=a).json()["items"]] == [cur]
    assert set(_posts(client, a)) == {cur}


def test_direct_room_board_is_separate_and_private(client, trio, other_family):
    a, b, c = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    family_msg = _send(client, a, "가족방 공지")
    direct_msg = _send(client, a, "둘만의 공지", room_id=room)
    _pin(client, a, family_msg)
    _pin(client, a, direct_msg, room_id=room)
    assert set(_posts(client, a)) == {family_msg}  # 방마다 따로
    assert set(_posts(client, b, room_id=room)) == {direct_msg}
    assert (
        client.get(BOARD, params={"room_id": room}, headers=c).status_code == 404
    )  # 참여자가 아니면 방이 없는 것처럼
    assert client.get(BOARD, params={"room_id": room}, headers=other_family).status_code == 404
    direct_post = _posts(client, a, room_id=room)[direct_msg]["id"]
    assert (
        client.delete(f"{BOARD}/{direct_post}", params={"room_id": room}, headers=c).status_code
        == 404
    )
    assert (
        client.delete(f"{BOARD}/{direct_post}", headers=a).status_code == 404
    )  # 방 id 가 다르면 이 방의 글이 아니다
    assert (
        client.delete(f"{BOARD}/{direct_post}", params={"room_id": room}, headers=b).status_code
        == 204
    )


def test_other_family_cannot_read_or_delete(client, family, other_family):
    a, _, _ = family
    mid = _send(client, a, "우리 가족 공지")
    _pin(client, a, mid)
    post_id = _posts(client, a)[mid]["id"]
    assert client.delete(f"{BOARD}/{post_id}", headers=other_family).status_code == 404
    assert _posts(client, a)[mid]["id"] == post_id


def test_requires_login_and_unknown_post(client, family):
    a, _, _ = family
    assert client.get(BOARD).status_code == 401
    assert client.delete(f"{BOARD}/abc").status_code == 401
    assert client.delete(f"{BOARD}/없는글", headers=a).status_code == 404


def test_already_pinned_without_a_post_creates_it(client, family):
    """옛 공지(기록이 없는 고정)를 다시 올리면 게시판 기록이 만들어진다."""
    a, _, _ = family
    mid = _send(client, a, "옛 공지")
    _pin(client, a, mid)
    with SessionLocal() as db:
        db.execute(ChatBoardPost.__table__.delete())
        db.commit()
    assert _posts(client, a) == {}
    again = _pin(client, a, mid)
    assert again["already_pinned"] is True
    assert mid in _posts(client, a)


def test_hidden_and_text_limit_do_not_leak_into_board(client, family):
    a, _, _ = family
    mid = _send(client, a, "나만 숨길 공지")
    _pin(client, a, mid)
    assert client.put(f"{PINS}/{mid}/hide", headers=a).status_code == 200
    # 나만 숨기기는 고정 바용이라 게시판 목록에는 그대로 있다
    assert mid in _posts(client, a)
