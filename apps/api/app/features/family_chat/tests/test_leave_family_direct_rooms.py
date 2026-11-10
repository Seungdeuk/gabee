"""가족 나가기(POST /family-group/groups/me/leave)와 1:1 방: 가족을 나가면 그 사람의 1:1 방 참여도 함께 지워진다(제품 결정 2026-11-10).
남은 상대는 "상대가 나간" 읽기 전용 방을 보고, 두 사람이 모두 없어지면 방과 하위 데이터(메시지·사진)가 지워진다. 다시 가입해도 옛 1:1 방은 이어지지 않는다."""

import io

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.features.family_chat.models import (
    ChatRoom,
    ChatRoomMember,
    ChatRoomMute,
    ChatRoomRead,
    Message,
    MessageAttachment,
)
from app.features.family_group.models import Group
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.helpers import join_family, signup

MSG = "/family-chat/messages"
ROOMS = "/family-chat/rooms"
DIRECT_ROOM = "/family-chat/rooms/direct"
LEAVE_FAMILY = "/family-group/groups/me/leave"


@pytest.fixture
def trio(client, family):
    a, b, group = family  # a(지민)는 소유자, b(수진)·c(삼촌)는 구성원
    c = signup(client, "삼촌")
    assert join_family(client, a, group["invite_code"], c).status_code == 200
    return a, b, c, group


def _uid(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def _direct(client, headers, peer_id):
    r = client.post(DIRECT_ROOM, json={"user_id": peer_id}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _rooms(client, headers):
    return {r["id"]: r for r in client.get(ROOMS, headers=headers).json()}


def _say(client, headers, room_id, text):
    return client.post(MSG, json={"text": text, "room_id": room_id}, headers=headers)


def _leave_family(client, headers):
    return client.post(LEAVE_FAMILY, headers=headers)


def _count(db, model, **where):
    stmt = select(func.count()).select_from(model)
    for column, value in where.items():
        stmt = stmt.where(getattr(model, column) == value)
    return db.scalar(stmt)


def test_leaving_the_family_removes_my_direct_room_and_the_peer_is_read_only(client, trio):
    a, b, c, _ = trio
    b_id, c_id = _uid(client, b), _uid(client, c)
    room = _direct(client, b, c_id)
    assert _say(client, b, room["id"], "안녕").status_code == 201
    assert _say(client, c, room["id"], "응").status_code == 201

    assert _leave_family(client, b).status_code == 204

    with SessionLocal() as db:  # 나간 사람의 방 참여가 지워졌다
        assert _count(db, ChatRoomMember, room_id=room["id"], user_id=b_id) == 0
        assert _count(db, ChatRoomMember, room_id=room["id"], user_id=c_id) == 1
        assert db.get(ChatRoom, room["id"]).direct_key.startswith(f"left:{b_id}:")
    mine = _rooms(client, c)[room["id"]]  # 상대는 읽기 전용 방을 그대로 본다
    assert mine["peer_left"] is True and mine["peer_user_id"] == b_id
    texts = [m["text"] for m in client.get(MSG, params={"room_id": room["id"]}, headers=c).json()]
    assert texts == ["안녕", "응"]
    r = _say(client, c, room["id"], "아직 있어?")
    assert r.status_code == 409 and r.json()["code"] == "peer_left_room", r.text


def test_my_read_marker_and_mute_in_the_direct_room_go_with_me(client, trio):
    a, b, c, _ = trio
    b_id = _uid(client, b)
    room = _direct(client, c, b_id)
    sent = _say(client, c, room["id"], "읽어 줘")
    assert sent.status_code == 201
    assert (
        client.put(f"{ROOMS}/{room['id']}/mute", json={"muted": True}, headers=b).status_code == 200
    )
    marked = client.post(
        "/family-chat/read",
        json={"message_id": sent.json()["id"], "room_id": room["id"]},
        headers=b,
    )
    assert marked.status_code == 200, marked.text

    assert _leave_family(client, b).status_code == 204

    with SessionLocal() as db:
        assert _count(db, ChatRoomMute, room_id=room["id"], user_id=b_id) == 0
        assert _count(db, ChatRoomRead, room_id=room["id"], user_id=b_id) == 0


def test_when_the_peer_already_left_the_room_leaving_the_family_deletes_everything(
    client, trio, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    a, b, c, _ = trio
    c_id = _uid(client, c)
    room = _direct(client, b, c_id)
    assert _say(client, b, room["id"], "지워질 대화").status_code == 201
    out = io.BytesIO()
    Image.new("RGB", (32, 32), (9, 9, 9)).save(out, format="JPEG")
    photo = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        data={"room_id": room["id"]},
        headers=b,
    )
    assert photo.status_code == 201, photo.text
    attachment_id = photo.json()["attachment"]["id"]
    assert list((tmp_path / "chat_photos").glob(f"{attachment_id}*"))
    left = client.post(f"{ROOMS}/{room['id']}/leave", headers=c)  # 상대가 먼저 방을 나갔다
    assert left.status_code == 204

    assert _leave_family(client, b).status_code == 204  # 마지막 사람이 가족을 나간다

    with SessionLocal() as db:
        assert db.get(ChatRoom, room["id"]) is None
        assert _count(db, Message, room_id=room["id"]) == 0
        assert _count(db, MessageAttachment, room_id=room["id"]) == 0
        assert _count(db, ChatRoomMember, room_id=room["id"]) == 0
    assert not list((tmp_path / "chat_photos").glob(f"{attachment_id}*"))  # 사진 파일도 지워진다


def test_every_direct_room_of_the_leaver_is_handled(client, trio):
    a, b, c, _ = trio
    a_id, b_id, c_id = _uid(client, a), _uid(client, b), _uid(client, c)
    with_a = _direct(client, b, a_id)  # 상대가 남아 있는 방
    with_c = _direct(client, b, c_id)  # 상대가 남아 있는 방
    assert _say(client, b, with_a["id"], "지민에게").status_code == 201
    a_c = _direct(client, c, a_id)  # c 의 또 다른 방: 상대(a)가 이미 방을 나간 방
    assert client.post(f"{ROOMS}/{a_c['id']}/leave", headers=a).status_code == 204

    assert (
        _leave_family(client, c).status_code == 204
    )  # c 의 방: with_c(상대 b 남음), a_c(상대 나감 → 삭제)

    with SessionLocal() as db:
        assert db.get(ChatRoom, a_c["id"]) is None
        assert db.get(ChatRoom, with_c["id"]) is not None
        assert _count(db, ChatRoomMember, room_id=with_c["id"], user_id=c_id) == 0
        assert _count(db, ChatRoomMember, room_id=with_c["id"], user_id=b_id) == 1
        assert _count(db, ChatRoomMember, room_id=with_a["id"]) == 2  # c 와 무관한 방
    rooms_b = _rooms(client, b)
    assert rooms_b[with_c["id"]]["peer_left"] is True
    assert rooms_b[with_a["id"]]["peer_left"] is False


def test_the_family_room_other_rooms_and_other_peoples_rooms_are_untouched(client, trio):
    a, b, c, _ = trio
    a_id, b_id = _uid(client, a), _uid(client, b)
    family_post = client.post(MSG, json={"text": "가족방 글"}, headers=b)
    assert family_post.status_code == 201, family_post.text
    other = _direct(client, a, _uid(client, c))  # b 와 무관한 방
    assert _say(client, a, other["id"], "남의 방").status_code == 201
    mine = _direct(client, b, a_id)

    assert _leave_family(client, b).status_code == 204

    with SessionLocal() as db:
        assert _count(db, ChatRoomMember, room_id=other["id"]) == 2
        assert db.get(ChatRoom, other["id"]).direct_key.startswith("left:") is False
        assert db.get(ChatRoom, mine["id"]) is not None  # 상대(a)는 읽기 전용 방을 남긴다
        assert _count(db, ChatRoomMember, room_id=mine["id"], user_id=b_id) == 0
        # 가족방 글은 그대로 남는다(지난 채팅은 그대로 둔다는 기존 결정)
        assert _count(db, Message, user_id=b_id, text="가족방 글") == 1
    texts = [m["text"] for m in client.get(MSG, headers=a).json()]
    assert "가족방 글" in texts
    assert [
        m["text"] for m in client.get(MSG, params={"room_id": other["id"]}, headers=a).json()
    ] == ["남의 방"]


def test_leaving_the_family_twice_is_not_a_server_error(client, trio):
    a, b, c, _ = trio
    _direct(client, b, _uid(client, c))
    assert _leave_family(client, b).status_code == 204
    again = _leave_family(client, b)
    # 순차 호출은 활성 가족이 이미 비어 400 no_group (동시 호출이 멤버십 행에서 기다리면 403 not_member)
    assert again.status_code == 400 and again.json()["code"] == "no_group", again.text


def test_rejoining_the_family_does_not_bring_the_old_direct_room_back(client, trio):
    a, b, c, group = trio
    b_id, c_id = _uid(client, b), _uid(client, c)
    old = _direct(client, c, b_id)
    assert _say(client, c, old["id"], "옛 대화").status_code == 201
    assert _leave_family(client, b).status_code == 204

    assert join_family(client, a, group["invite_code"], b).status_code == 200

    assert old["id"] not in _rooms(client, b)  # 옛 방은 보이지 않는다
    r = client.get(MSG, params={"room_id": old["id"]}, headers=b)
    assert r.status_code == 404
    assert _say(client, b, old["id"], "몰래").status_code == 404
    fresh = _direct(client, b, c_id)  # 새 대화는 빈 새 방이다
    assert fresh["id"] != old["id"] and fresh["last_message"] is None
    rooms_c = _rooms(client, c)  # 상대는 나간 옛 방(읽기 전용)과 새 방을 둘 다 본다
    assert rooms_c[old["id"]]["peer_left"] is True and rooms_c[fresh["id"]]["peer_left"] is False


def test_the_last_owner_deleting_the_family_still_purges_rooms(
    client, family, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    a, b, group = family
    a_id, b_id = _uid(client, a), _uid(client, b)
    room = _direct(client, a, b_id)
    assert _say(client, a, room["id"], "곧 지워질 대화").status_code == 201
    assert _leave_family(client, b).status_code == 204  # b 가 나가면 방은 a 만 남는다
    with SessionLocal() as db:
        assert _count(db, ChatRoomMember, room_id=room["id"], user_id=a_id) == 1

    assert _leave_family(client, a).status_code == 204  # 혼자 남은 소유자가 나가면 가족을 지운다

    with SessionLocal() as db:
        assert db.get(Group, group["id"]) is None
        assert db.get(ChatRoom, room["id"]) is None
        assert _count(db, Message, room_id=room["id"]) == 0
        assert _count(db, ChatRoomMember, room_id=room["id"]) == 0


def test_if_the_room_cleanup_fails_leaving_the_family_is_rolled_back(client, trio, monkeypatch):
    from app.features.family_group.models import GroupMember
    from app.shared import member_exit

    a, b, c, group = trio
    b_id = _uid(client, b)
    room = _direct(client, c, b_id)

    def boom(db, group_id, user_id):
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(member_exit, "_handlers", [boom])
    with pytest.raises(RuntimeError):
        _leave_family(client, b)

    with SessionLocal() as db:  # 반쪽 상태 없이 그대로다: 가족 구성원이고 방 참여도 남아 있다
        assert (
            db.scalar(
                select(func.count())
                .select_from(GroupMember)
                .where(GroupMember.group_id == group["id"], GroupMember.user_id == b_id)
            )
            == 1
        )
        assert _count(db, ChatRoomMember, room_id=room["id"], user_id=b_id) == 1
