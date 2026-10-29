"""메시지 반응: 한 사람이 한 메시지에 하나(바꾸면 교체), 이모지 6개만, 방 접근 규칙은 조회와 같고, 지운 메시지에는 못 한다."""

import httpx
import pytest
from sqlalchemy import event, func, select

from app.features.family_chat.assistant import post_as_assistant
from app.features.family_chat.models import Message, MessageReaction
from app.shared.db import SessionLocal, engine
from app.shared.llm import client as llm
from tests.helpers import join_family, signup

MSG = "/family-chat/messages"
DIRECT_ROOM = "/family-chat/rooms/direct"
HEART = "❤️"  # ❤️
THUMB = "👍"


@pytest.fixture(autouse=True)
def _no_ai(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)


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


def _react(client, headers, message_id, emoji, room_id=None):
    params = {"room_id": room_id} if room_id else None
    return client.put(
        f"{MSG}/{message_id}/reaction", json={"emoji": emoji}, params=params, headers=headers
    )


def _unreact(client, headers, message_id, room_id=None):
    params = {"room_id": room_id} if room_id else None
    return client.delete(f"{MSG}/{message_id}/reaction", params=params, headers=headers)


def _msg(client, headers, message_id, **params):
    r = client.get(MSG, params={"latest": True, **params}, headers=headers)
    assert r.status_code == 200, r.text
    return {m["id"]: m for m in r.json()}[message_id]


def test_react_returns_message_with_my_reaction(client, family):
    a, _, _ = family
    mid = _send(client, a, "점심 먹었어?")
    r = _react(client, a, mid, THUMB)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == mid
    assert r.json()["reactions"] == [{"emoji": THUMB, "count": 1, "mine": True}]


def test_message_without_reactions_has_empty_list(client, family):
    a, _, _ = family
    mid = _send(client, a, "그냥 메시지")
    assert _msg(client, a, mid)["reactions"] == []


def test_counts_and_mine_are_per_viewer(client, trio):
    a, b, c = trio
    mid = _send(client, a, "다들 모여")
    assert _react(client, b, mid, HEART).status_code == 200
    assert _react(client, c, mid, HEART).status_code == 200
    assert _react(client, a, mid, THUMB).status_code == 200  # 내 메시지에도 반응할 수 있다
    for headers, mine in ((a, THUMB), (b, HEART), (c, HEART)):
        reactions = _msg(client, headers, mid)["reactions"]
        assert {r["emoji"]: r["count"] for r in reactions} == {HEART: 2, THUMB: 1}
        assert [r["emoji"] for r in reactions if r["mine"]] == [mine]
    assert _msg(client, a, mid)["reactions"][0] == {
        "emoji": HEART,
        "count": 2,
        "mine": False,
    }  # 많은 순


def test_one_reaction_per_user_and_changing_replaces(client, family):
    a, _, _ = family
    mid = _send(client, a, "한 사람에 하나")
    assert _react(client, a, mid, THUMB).status_code == 200
    r = _react(client, a, mid, HEART)
    assert r.json()["reactions"] == [{"emoji": HEART, "count": 1, "mine": True}]
    with SessionLocal() as db:
        assert db.scalar(select(func.count(MessageReaction.message_id))) == 1


def test_same_reaction_again_is_idempotent(client, family):
    a, _, _ = family
    mid = _send(client, a, "두 번 눌러도")
    assert _react(client, a, mid, THUMB).status_code == 200
    again = _react(client, a, mid, THUMB)
    assert again.status_code == 200
    assert again.json()["reactions"] == [{"emoji": THUMB, "count": 1, "mine": True}]


def test_remove_reaction_and_remove_is_idempotent(client, family):
    a, b, _ = family
    mid = _send(client, a, "취소 시험")
    _react(client, a, mid, THUMB)
    _react(client, b, mid, THUMB)
    r = _unreact(client, a, mid)
    assert r.status_code == 200
    assert r.json()["reactions"] == [
        {"emoji": THUMB, "count": 1, "mine": False}
    ]  # 남의 반응은 그대로
    assert _unreact(client, a, mid).status_code == 200  # 이미 없어도 같은 결과


def test_only_six_emojis_are_allowed(client, family):
    a, _, _ = family
    mid = _send(client, a, "허용 목록")
    for ok in ("❤️", "👍", "😂", "😮", "😢", "🙏"):
        assert _react(client, a, mid, ok).status_code == 200, ok
    for bad in ("🔥", "a", "", "👍👍", "<script>"):
        r = _react(client, a, mid, bad)
        assert r.status_code in (400, 422), bad
    assert _react(client, a, mid, "🔥").json()["code"] == "invalid_reaction"


def test_heart_without_variation_selector_is_normalized(client, family):
    a, _, _ = family
    mid = _send(client, a, "하트 표기")
    r = _react(client, a, mid, "❤")  # 변형 문자 없는 ❤
    assert r.status_code == 200 and r.json()["reactions"][0]["emoji"] == HEART


def test_cannot_react_to_deleted_message_and_delete_clears_reactions(client, family):
    a, b, _ = family
    mid = _send(client, a, "지울 메시지")
    _react(client, b, mid, THUMB)
    assert client.delete(f"{MSG}/{mid}", headers=a).status_code == 200
    with SessionLocal() as db:
        assert (
            db.scalar(select(func.count(MessageReaction.message_id))) == 0
        )  # 지우면 반응도 남기지 않는다
    r = _react(client, b, mid, HEART)
    assert r.status_code == 400 and r.json()["code"] == "message_deleted"
    assert _msg(client, b, mid)["reactions"] == []


def test_unknown_message_other_family_and_login(client, family, other_family):
    a, _, _ = family
    mid = _send(client, a, "우리 가족 메시지")
    assert _react(client, a, 999999, THUMB).status_code == 404
    assert _react(client, other_family, mid, THUMB).status_code == 404  # 존재 여부를 숨긴다
    assert _unreact(client, other_family, mid).status_code == 404
    assert client.put(f"{MSG}/{mid}/reaction", json={"emoji": THUMB}).status_code == 401
    assert client.delete(f"{MSG}/{mid}/reaction").status_code == 401


def test_direct_room_reactions_respect_room_access(client, trio):
    a, b, c = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    mid = _send(client, a, "둘만의 대화", room_id=room)
    assert (
        _react(client, c, mid, THUMB, room_id=room).status_code == 404
    )  # 참여자가 아니면 방이 없는 것처럼
    assert (
        _react(client, c, mid, THUMB).status_code == 404
    )  # 가족방 기준으로도 이 방 메시지가 아니다
    assert _react(client, b, mid, THUMB, room_id=room).status_code == 200
    assert _msg(client, a, mid, room_id=room)["reactions"][0]["count"] == 1


def test_message_of_other_room_cannot_be_reacted_through_wrong_room(client, trio):
    a, b, _ = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    mid = _send(client, a, "가족방 메시지")
    assert _react(client, a, mid, THUMB, room_id=room).status_code == 404


def test_can_react_to_assistant_message(client, family):
    a, _, _ = family
    with SessionLocal() as db:
        gid = db.get(Message, _send(client, a, "처음")).group_id
        posted = post_as_assistant(db, gid, "도와드릴게요")
    assert _react(client, a, posted.id, "🙏").json()["reactions"][0]["emoji"] == "🙏"


def test_reactions_show_in_before_and_around_pages(client, family):
    a, b, _ = family
    ids = [_send(client, a, f"메시지 {i}") for i in range(5)]
    _react(client, b, ids[2], THUMB)
    around = client.get(MSG, params={"around_id": ids[2], "limit": 4}, headers=a).json()
    assert {m["id"]: m["reactions"] for m in around}[ids[2]][0]["emoji"] == THUMB
    before = client.get(MSG, params={"before_id": ids[4], "limit": 5}, headers=a).json()
    assert {m["id"]: m["reactions"] for m in before}[ids[2]][0]["count"] == 1


def test_listing_reactions_uses_one_query(client, trio):
    a, b, c = trio
    ids = [_send(client, a, f"메시지 {i}") for i in range(8)]
    for mid in ids:
        _react(client, b, mid, THUMB)
        _react(client, c, mid, HEART)
    statements: list[str] = []

    def count(conn, cursor, statement, params, context, executemany):
        if "message_reactions" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        listed = client.get(MSG, params={"latest": True}, headers=a).json()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert all(len(m["reactions"]) == 2 for m in listed if m["id"] in ids)
    assert len(statements) == 1, statements  # 메시지 수와 상관없이 한 번에 모아 센다


def test_room_list_last_message_has_no_reactions_field_filled(client, family):
    a, b, _ = family
    mid = _send(client, a, "마지막 메시지")
    _react(client, b, mid, THUMB)
    last = client.get("/family-chat/rooms", headers=a).json()[0]["last_message"]
    assert (
        last["id"] == mid and last["reactions"] == []
    )  # 방 목록 미리보기에는 반응을 붙이지 않는다
