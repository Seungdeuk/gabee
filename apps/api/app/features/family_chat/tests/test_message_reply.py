"""메시지 답장: 같은 방의 메시지에만, 지운 메시지에는 못 하고, 응답에 원본 미리보기(지워지면 내용 없음)가 붙는다."""

import io

import httpx
import pytest
from PIL import Image
from sqlalchemy import event

from app.features.family_chat.assistant import post_as_assistant
from app.features.family_chat.models import Message
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
    with SessionLocal() as db:
        gid = db.get(Message, _ok(client, a, "처음")["id"]).group_id
        posted = post_as_assistant(
            db, gid, "무엇을 도와드릴까요?"
        )  # 실제 서버가 가비 답을 저장하는 함수
    reply = _ok(client, a, "고마워", reply_to=posted.id)
    assert (
        reply["reply_to"]["user_name"] == "가비"
        and reply["reply_to"]["text"] == "무엇을 도와드릴까요?"
    )


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
    """원본이 여럿이고 목록 페이지 밖에 있어도 원본·이름·첨부는 한 번씩만 모아 조회한다(N+1 방지)."""
    a, b, _ = family
    parents = [_ok(client, a, f"원본 {i}") for i in range(6)]
    for i, parent in enumerate(parents):
        _ok(client, b, f"답장 {i}", reply_to=parent["id"])
    statements: list[str] = []

    def count(conn, cursor, statement, params, context, executemany):
        if "FROM messages" in statement or "FROM message_attachments" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        listed = _list(client, a, limit=6)  # 최근 6개 = 답장 6개, 원본은 모두 페이지 밖
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert [m["reply_to"]["id"] for m in listed] == [p["id"] for p in parents]
    # 메시지 목록 1 + 첨부 1(목록) + 원본(이름 포함) 1 + 첨부 1(원본) 정도. 답장 수(6)에 비례하지 않는다
    assert len(statements) <= 5, statements


def test_reply_preview_never_crosses_rooms_even_if_row_is_tampered(client, trio):
    """원본 조회에도 방 조건을 걸어, DB 를 손으로 고쳐도 다른 방 메시지의 내용이 미리보기로 새지 않는다."""
    a, b, _ = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    secret = _ok(client, a, "둘만의 비밀", room_id=room)
    family_msg = _ok(client, a, "가족방 글")
    with SessionLocal() as db:
        db.get(Message, family_msg["id"]).reply_to_id = secret["id"]  # 검증을 건너뛴 잘못된 데이터
        db.commit()
    shown = {m["id"]: m for m in _list(client, b)}[family_msg["id"]]
    assert shown["reply_to"] is None
    assert "둘만의 비밀" not in str(_list(client, b))


def test_deleted_reply_drops_its_reply_link(client, family):
    a, b, _ = family
    parent = _ok(client, a, "원본")
    reply = _ok(client, b, "답장", reply_to=parent["id"])
    deleted = _delete(client, b, reply["id"])
    assert deleted.status_code == 200 and deleted.json()["reply_to"] is None
    assert {m["id"]: m for m in _list(client, a)}[reply["id"]]["reply_to"] is None
    with SessionLocal() as db:
        assert (
            db.get(Message, reply["id"]).reply_to_id is None
        )  # 지우면 어느 글에 답했는지도 남기지 않는다


def test_reply_preview_in_before_and_around_pages(client, family):
    a, b, _ = family
    parent = _ok(client, a, "원본")
    replies = [_ok(client, b, f"답장 {i}", reply_to=parent["id"]) for i in range(3)]
    around = client.get(MSG, params={"around_id": replies[1]["id"], "limit": 4}, headers=a).json()
    assert all(
        m["reply_to"]["id"] == parent["id"] for m in around if m["id"] in {r["id"] for r in replies}
    )
    before = client.get(
        MSG, params={"before_id": replies[2]["id"] + 1, "limit": 5}, headers=a
    ).json()
    assert [m["reply_to"]["id"] for m in before if m["id"] in {r["id"] for r in replies}] == [
        parent["id"]
    ] * 3


def test_room_list_last_message_has_no_reply_preview(client, family):
    a, b, _ = family
    parent = _ok(client, a, "원본")
    _ok(client, b, "답장", reply_to=parent["id"])
    last = client.get("/family-chat/rooms", headers=a).json()[0]["last_message"]
    assert last["text"] == "답장" and last["reply_to"] is None  # 방 목록 미리보기에는 붙이지 않는다


def test_deleting_photo_original_clears_attachment_flag(client, family):
    a, b, _ = family
    photo = _photo(client, a)
    reply = _ok(client, b, "예쁘다", reply_to=photo["id"])
    assert reply["reply_to"]["has_attachment"] is True
    assert _delete(client, a, photo["id"]).status_code == 200
    shown = {m["id"]: m for m in _list(client, b)}[reply["id"]]
    assert shown["reply_to"]["deleted"] is True and shown["reply_to"]["has_attachment"] is False
