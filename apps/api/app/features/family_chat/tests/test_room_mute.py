"""채팅방 알림 끄기: 방·사용자별 설정 저장(기본 켜짐), 목록·방 열기 응답, 접근 제한. 읽지 않은 수는 그대로."""

import pytest

from app.features.family_chat.models import FAMILY
from tests.helpers import join_family, signup

MSG = "/family-chat/messages"
ROOMS = "/family-chat/rooms"
DIRECT_ROOM = "/family-chat/rooms/direct"


def _mute_url(room_id):
    return f"{ROOMS}/{room_id}/mute"


@pytest.fixture
def trio(client, family):
    """같은 가족 구성원 셋(지민 a, 수진 b, 삼촌 c)."""
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


def _family_room(client, headers):
    rooms = client.get(ROOMS, headers=headers).json()
    return next(r for r in rooms if r["kind"] == FAMILY)


def _by_id(client, headers):
    return {r["id"]: r for r in client.get(ROOMS, headers=headers).json()}


def test_default_is_not_muted(client, trio):
    a, b, _ = trio
    direct = _direct(client, a, _uid(client, b))
    assert direct["muted"] is False
    assert all(r["muted"] is False for r in client.get(ROOMS, headers=a).json())


def test_mute_family_room_and_unmute_idempotent(client, family):
    a, b, _ = family
    room_id = _family_room(client, a)["id"]
    for _ in range(2):  # 멱등
        r = client.put(_mute_url(room_id), json={"muted": True}, headers=a)
        assert r.status_code == 200, r.text
        assert r.json() == {"room_id": room_id, "muted": True}
    assert _family_room(client, a)["muted"] is True
    for _ in range(2):
        r = client.put(_mute_url(room_id), json={"muted": False}, headers=a)
        assert r.status_code == 200, r.text
        assert r.json() == {"room_id": room_id, "muted": False}
    assert _family_room(client, a)["muted"] is False


def test_mute_direct_room_shows_in_list_and_open(client, trio):
    a, b, c = trio
    direct = _direct(client, a, _uid(client, b))
    other = _direct(client, a, _uid(client, c))
    r = client.put(_mute_url(direct["id"]), json={"muted": True}, headers=a)
    assert r.status_code == 200 and r.json()["muted"] is True
    rooms = _by_id(client, a)
    assert rooms[direct["id"]]["muted"] is True
    assert rooms[other["id"]]["muted"] is False
    assert _family_room(client, a)["muted"] is False
    assert _direct(client, a, _uid(client, b))["muted"] is True  # 방 열기 응답
    assert client.put(_mute_url(direct["id"]), json={"muted": False}, headers=a).status_code == 200
    assert _by_id(client, a)[direct["id"]]["muted"] is False


def test_other_users_mute_does_not_affect_me(client, family):
    a, b, _ = family
    room_id = _family_room(client, a)["id"]
    assert client.put(_mute_url(room_id), json={"muted": True}, headers=b).status_code == 200
    assert _family_room(client, a)["muted"] is False
    assert _family_room(client, b)["muted"] is True
    # 내가 끄거나 켜도 상대 설정은 그대로
    assert client.put(_mute_url(room_id), json={"muted": True}, headers=a).status_code == 200
    assert client.put(_mute_url(room_id), json={"muted": False}, headers=a).status_code == 200
    assert _family_room(client, b)["muted"] is True


def test_mute_keeps_unread_count(client, family):
    a, b, _ = family
    room_id = _family_room(client, a)["id"]
    client.post(MSG, json={"text": "안녕"}, headers=b)
    assert client.put(_mute_url(room_id), json={"muted": True}, headers=a).status_code == 200
    room = _family_room(client, a)
    assert room["muted"] is True and room["unread"] == 1


def test_cannot_mute_room_i_cannot_see(client, trio):
    a, b, c = trio
    ab = _direct(client, a, _uid(client, b))
    r = client.put(_mute_url(ab["id"]), json={"muted": True}, headers=c)  # 참여자가 아닌 1:1 방
    assert r.status_code == 404
    assert _by_id(client, a)[ab["id"]]["muted"] is False
    r = client.put(_mute_url("nope"), json={"muted": True}, headers=a)
    assert r.status_code == 404


def test_cannot_mute_other_family_room(client, family, other_family):
    a, _, _ = family
    other = other_family
    other_room = _family_room(client, other)
    assert other_room["kind"] == FAMILY
    r = client.put(_mute_url(other_room["id"]), json={"muted": True}, headers=a)
    assert r.status_code == 404
    assert _family_room(client, other)["muted"] is False


def test_mute_requires_body_and_login(client, family):
    a, _, _ = family
    room_id = _family_room(client, a)["id"]
    assert client.put(_mute_url(room_id), json={}, headers=a).status_code == 422
    assert client.put(_mute_url(room_id), json={"muted": True}).status_code == 401
