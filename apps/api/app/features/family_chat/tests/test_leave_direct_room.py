"""1:1 채팅방 나가기(POST /family-chat/rooms/{id}/leave): 나가면 내 목록에서 사라지고, 상대는 기록을 그대로 갖되 "상대가 나갔다"는 표시와
함께 새 메시지를 보낼 수 없다. 둘 다 나가면 대화와 사진 파일이 모두 지워진다. 나간 뒤 같은 상대와 새 대화를 열면 빈 새 방이다."""

import io

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.features.family_chat.models import (
    FAMILY,
    ChatRoom,
    ChatRoomMember,
    ChatRoomMute,
    ChatRoomRead,
    Message,
    MessageAttachment,
)
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.helpers import join_family, signup

MSG = "/family-chat/messages"
ROOMS = "/family-chat/rooms"
DIRECT_ROOM = "/family-chat/rooms/direct"


@pytest.fixture
def trio(client, family):
    a, b, group = family
    c = signup(client, "삼촌")
    assert join_family(client, a, group["invite_code"], c).status_code == 200
    return a, b, c


def _uid(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def _direct(client, headers, peer_id):
    r = client.post(DIRECT_ROOM, json={"user_id": peer_id}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _rooms(client, headers):
    return {r["id"]: r for r in client.get(ROOMS, headers=headers).json()}


def _leave(client, headers, room_id):
    return client.post(f"{ROOMS}/{room_id}/leave", headers=headers)


def _say(client, headers, room_id, text):
    return client.post(MSG, json={"text": text, "room_id": room_id}, headers=headers)


def test_leaving_removes_the_room_for_me_but_the_peer_keeps_the_record(client, trio):
    a, b, _ = trio
    a_id, b_id = _uid(client, a), _uid(client, b)
    room = _direct(client, a, b_id)
    assert _say(client, a, room["id"], "안녕").status_code == 201
    assert _say(client, b, room["id"], "응").status_code == 201

    assert _leave(client, a, room["id"]).status_code == 204

    assert room["id"] not in _rooms(client, a)  # 내 목록에서 사라진다
    assert (
        client.get(MSG, params={"room_id": room["id"]}, headers=a).status_code == 404
    )  # 더는 들어갈 수 없다
    mine = _rooms(client, b)[room["id"]]  # 상대에게는 방이 그대로 있다
    assert mine["peer_left"] is True and mine["peer_user_id"] == a_id  # 나간 사람을 알려 준다
    texts = [m["text"] for m in client.get(MSG, params={"room_id": room["id"]}, headers=b).json()]
    assert texts == ["안녕", "응"]  # 기록은 그대로


def test_the_peer_cannot_send_to_a_room_the_other_person_left(client, trio):
    a, b, _ = trio
    room = _direct(client, a, _uid(client, b))
    assert _leave(client, a, room["id"]).status_code == 204
    r = _say(client, b, room["id"], "아직 있어?")
    assert r.status_code == 409 and r.json()["code"] == "peer_left_room", r.text
    out = io.BytesIO()
    Image.new("RGB", (32, 32), (9, 9, 9)).save(out, format="JPEG")
    photo = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        data={"room_id": room["id"]},
        headers=b,
    )
    assert photo.status_code == 409 and photo.json()["code"] == "peer_left_room", photo.text


def test_opening_a_new_chat_with_the_same_person_makes_a_new_empty_room(client, trio):
    a, b, _ = trio
    b_id = _uid(client, b)
    old = _direct(client, a, b_id)
    assert _say(client, a, old["id"], "옛날 대화").status_code == 201
    assert _leave(client, a, old["id"]).status_code == 204

    fresh = _direct(client, a, b_id)
    assert (
        fresh["id"] != old["id"] and fresh["last_message"] is None and fresh["peer_left"] is False
    )
    assert _say(client, a, fresh["id"], "새 대화").status_code == 201
    mine = _rooms(client, b)  # 상대는 나간 옛 방(읽기 전용)과 새 방을 둘 다 본다
    assert mine[old["id"]]["peer_left"] is True and mine[fresh["id"]]["peer_left"] is False


def test_the_family_room_cannot_be_left(client, trio):
    a, _, _ = trio
    family_room = next(r for r in _rooms(client, a).values() if r["kind"] == FAMILY)
    r = _leave(client, a, family_room["id"])
    assert r.status_code == 400 and r.json()["code"] == "cannot_leave_family_room", r.text


def test_a_room_you_are_not_in_is_a_404_and_leaving_twice_is_a_404(client, trio):
    a, b, c = trio
    room = _direct(client, a, _uid(client, b))
    assert _leave(client, c, room["id"]).status_code == 404  # 남의 방은 존재 여부를 숨긴다
    assert _leave(client, a, room["id"]).status_code == 204
    assert _leave(client, a, room["id"]).status_code == 404  # 이미 나갔다


def test_my_read_marker_and_mute_are_removed_when_i_leave(client, trio):
    a, b, _ = trio
    room = _direct(client, a, _uid(client, b))
    sent = _say(client, b, room["id"], "읽어 줘")
    assert sent.status_code == 201
    assert (
        client.put(f"{ROOMS}/{room['id']}/mute", json={"muted": True}, headers=a).status_code == 200
    )
    marked = client.post(
        "/family-chat/read",
        json={"message_id": sent.json()["id"], "room_id": room["id"]},
        headers=a,
    )
    assert marked.status_code == 200, marked.text
    with SessionLocal() as db:  # 지우기 전에는 읽음 표시와 알림 끄기가 있다
        assert (
            db.scalar(
                select(func.count())
                .select_from(ChatRoomMute)
                .where(ChatRoomMute.room_id == room["id"])
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ChatRoomRead)
                .where(ChatRoomRead.room_id == room["id"], ChatRoomRead.user_id == _uid(client, a))
            )
            == 1
        )
    assert _leave(client, a, room["id"]).status_code == 204
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ChatRoomMute)
                .where(ChatRoomMute.room_id == room["id"])
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ChatRoomRead)
                .where(ChatRoomRead.room_id == room["id"], ChatRoomRead.user_id == _uid(client, a))
            )
            == 0
        )


def test_when_both_have_left_everything_in_the_room_is_deleted(client, trio, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    a, b, c = trio
    b_id, c_id = _uid(client, b), _uid(client, c)
    room = _direct(client, a, b_id)
    other = _direct(client, a, c_id)  # 다른 1:1 방은 그대로 남아야 한다
    assert _say(client, a, room["id"], "지워질 대화").status_code == 201
    assert _say(client, a, other["id"], "남을 대화").status_code == 201
    out = io.BytesIO()
    Image.new("RGB", (32, 32), (9, 9, 9)).save(out, format="JPEG")
    photo = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        data={"room_id": room["id"]},
        headers=a,
    )
    assert photo.status_code == 201, photo.text
    attachment_id = photo.json()["attachment"]["id"]
    assert list((tmp_path / "chat_photos").glob(f"{attachment_id}*"))

    assert _leave(client, a, room["id"]).status_code == 204
    assert _leave(client, b, room["id"]).status_code == 204  # 마지막 사람이 나간다

    with SessionLocal() as db:
        assert db.get(ChatRoom, room["id"]) is None
        assert (
            db.scalar(
                select(func.count()).select_from(Message).where(Message.room_id == room["id"])
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(MessageAttachment)
                .where(MessageAttachment.room_id == room["id"])
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ChatRoomMember)
                .where(ChatRoomMember.room_id == room["id"])
            )
            == 0
        )
        assert db.get(ChatRoom, other["id"]) is not None  # 다른 방은 그대로
    assert not list((tmp_path / "chat_photos").glob(f"{attachment_id}*"))  # 사진 파일도 지워진다
    texts = [m["text"] for m in client.get(MSG, params={"room_id": other["id"]}, headers=a).json()]
    assert texts == ["남을 대화"]


@pytest.fixture
def enforce_foreign_keys():
    """SQLite 는 기본으로 외래 키를 검사하지 않아 삭제 순서 오류를 숨긴다. 이 시험 동안만 검사를 켠다(PostgreSQL 과 같게)."""
    from sqlalchemy import event

    from app.shared.db import engine

    def on_connect(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    event.listen(engine, "connect", on_connect)
    engine.dispose()
    yield
    event.remove(engine, "connect", on_connect)
    engine.dispose()


def test_deleting_a_room_with_reactions_and_replies_passes_foreign_key_checks(
    client, trio, enforce_foreign_keys
):
    a, b, _ = trio
    room = _direct(client, a, _uid(client, b))
    first = _say(client, a, room["id"], "처음")
    assert first.status_code == 201
    reply = client.post(
        MSG,
        json={"text": "답장", "room_id": room["id"], "reply_to_id": first.json()["id"]},
        headers=b,
    )
    assert reply.status_code == 201, reply.text
    react = client.put(
        f"/family-chat/messages/{first.json()['id']}/reaction",
        json={"emoji": "👍"},
        params={"room_id": room["id"]},
        headers=b,
    )
    assert react.status_code in (200, 204), react.text
    assert _leave(client, a, room["id"]).status_code == 204
    assert _leave(client, b, room["id"]).status_code == 204
    with SessionLocal() as db:
        assert db.get(ChatRoom, room["id"]) is None
