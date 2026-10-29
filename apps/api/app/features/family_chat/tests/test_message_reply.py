"""메시지 답장: 같은 방의 메시지에만, 지운 메시지에는 못 하고, 응답에 원본 미리보기(지워지면 내용 없음)가 붙는다."""

import io

import httpx
import pytest
from PIL import Image
from sqlalchemy import event

from app.features.family_chat.assistant import get_or_create_assistant
from app.features.family_chat.models import ASSISTANT_USER_ID, Message
from app.shared.config import settings
from app.shared.db import SessionLocal, engine
from app.shared.llm import client as llm
from tests.helpers import join_family, signup

MSG = "/family-chat/messages"
PHOTOS = "/family-chat/photos"
DIRECT_ROOM = "/family-chat/rooms/direct"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))

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


def _send(client, headers, text, room_id=None, reply_to=None):
    body = {"text": text}
    if room_id is not None:
        body["room_id"] = room_id
    if reply_to is not None:
        body["reply_to_id"] = reply_to
    return client.post(MSG, json=body, headers=headers)


def _ok(client, headers, text, **kw):
    r = _send(client, headers, text, **kw)
    assert r.status_code == 201, r.text
    return r.json()


def _photo(client, headers):
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(out, format="JPEG")
    r = client.post(
        PHOTOS, files={"file": ("a.jpg", out.getvalue(), "image/jpeg")}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


def _delete(client, headers, message_id):
    return client.delete(f"{MSG}/{message_id}", headers=headers)


def _list(client, headers, **params):
    r = client.get(MSG, params={"latest": True, **params}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_reply_carries_original_preview(client, family):
    a, b, _ = family
    parent = _ok(client, a, "저녁 뭐 먹을까?")
    reply = _ok(client, b, "김치찌개 어때?", reply_to=parent["id"])
    assert reply["reply_to"] == {
        "id": parent["id"],
        "user_name": "지민",
        "text": "저녁 뭐 먹을까?",
        "deleted": False,
        "has_attachment": False,
    }
    listed = {m["id"]: m for m in _list(client, a)}
    assert listed[reply["id"]]["reply_to"]["id"] == parent["id"]
    assert listed[parent["id"]]["reply_to"] is None  # 답장이 아닌 메시지는 null


def test_plain_message_has_no_reply(client, family):
    a, _, _ = family
    assert _ok(client, a, "그냥 메시지")["reply_to"] is None


def test_preview_text_is_shortened(client, family):
    a, b, _ = family
    parent = _ok(client, a, "가" * 100)
    reply = _ok(client, b, "답", reply_to=parent["id"])
    assert (
        reply["reply_to"]["text"] == "가" * 40
    )  # 미리보기는 40자까지(원문 전체는 원본 메시지에 있다)


def test_reply_to_photo_marks_attachment_without_text(client, family):
    a, b, _ = family
    photo = _photo(client, a)
    reply = _ok(client, b, "예쁘다", reply_to=photo["id"])
    assert reply["reply_to"]["has_attachment"] is True and reply["reply_to"]["text"] == ""


def test_reply_to_unknown_or_other_family_message_is_rejected(client, family, other_family):
    a, _, _ = family
    other = _ok(client, other_family, "다른 가족 메시지")
    for target in (999999, other["id"]):
        r = _send(client, a, "답장", reply_to=target)
        assert r.status_code == 400 and r.json()["code"] == "invalid_message"


def test_reply_must_stay_in_same_room(client, trio):
    a, b, _ = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    family_msg = _ok(client, a, "가족방 메시지")
    direct_msg = _ok(client, a, "둘만의 메시지", room_id=room)
    # 1:1 방에서 가족방 메시지에, 가족방에서 1:1 방 메시지에 답장할 수 없다
    r1 = _send(client, a, "교차 답장", room_id=room, reply_to=family_msg["id"])
    r2 = _send(client, a, "교차 답장", reply_to=direct_msg["id"])
    assert r1.status_code == 400 and r2.status_code == 400
    ok = _ok(client, b, "둘이서", room_id=room, reply_to=direct_msg["id"])
    assert ok["reply_to"]["text"] == "둘만의 메시지"


def test_third_member_cannot_reply_into_direct_room(client, trio):
    a, b, c = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    direct_msg = _ok(client, a, "둘만의 메시지", room_id=room)
    assert _send(client, c, "끼어들기", room_id=room, reply_to=direct_msg["id"]).status_code == 404


def test_cannot_reply_to_deleted_message(client, family):
    a, b, _ = family
    parent = _ok(client, a, "지울 메시지")
    assert _delete(client, a, parent["id"]).status_code == 200
    r = _send(client, b, "답장", reply_to=parent["id"])
    assert r.status_code == 400 and r.json()["code"] == "reply_deleted"


def test_reply_preview_empties_when_original_is_deleted_later(client, family):
    a, b, _ = family
    parent = _ok(client, a, "비밀 메시지")
    reply = _ok(client, b, "응", reply_to=parent["id"])
    assert _delete(client, a, parent["id"]).status_code == 200
    shown = {m["id"]: m for m in _list(client, b)}[reply["id"]]
    assert shown["reply_to"]["deleted"] is True and shown["reply_to"]["text"] == ""
    assert shown["reply_to"]["has_attachment"] is False


def test_can_reply_to_assistant_message(client, family):
    a, _, _ = family
    parent = _ok(client, a, "@가비 질문")
    with SessionLocal() as db:
        get_or_create_assistant(db)
        row = db.get(Message, parent["id"])
        row.user_id = ASSISTANT_USER_ID
        db.commit()
    reply = _ok(client, a, "고마워", reply_to=parent["id"])
    assert reply["reply_to"]["user_name"] == "가비"


def test_reply_to_a_reply_shows_only_direct_parent(client, family):
    a, b, _ = family
    first = _ok(client, a, "처음")
    second = _ok(client, b, "둘째", reply_to=first["id"])
    third = _ok(client, a, "셋째", reply_to=second["id"])
    assert third["reply_to"]["id"] == second["id"] and third["reply_to"]["text"] == "둘째"


def test_reply_to_id_validation(client, family):
    a, _, _ = family
    for bad in (0, -1, "abc"):
        r = client.post(MSG, json={"text": "답", "reply_to_id": bad}, headers=a)
        assert r.status_code == 422


def test_listing_replies_does_not_query_per_message(client, family):
    """답장이 여럿이어도 원본은 한 번의 쿼리로 모아 붙인다(N+1 방지)."""
    a, b, _ = family
    parent = _ok(client, a, "원본")
    for i in range(6):
        _ok(client, b, f"답장 {i}", reply_to=parent["id"])
    statements: list[str] = []

    def count(conn, cursor, statement, params, context, executemany):
        if "FROM messages" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        listed = _list(client, a)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len([m for m in listed if m["reply_to"]]) == 6
    assert (
        len(statements) <= 3
    )  # 메시지 목록 + 원본 묶음 조회(+ 방 확인). 메시지 수에 비례하지 않는다
