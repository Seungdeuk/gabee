"""대화방: 가족 전체방(기본), 1:1 방, 방별 메시지·읽음·접근 제한, 1:1 대화는 AI 로 가지 않는다."""

import httpx
import pytest
from sqlalchemy import select

from app.features.family_chat import ai_repository
from app.features.family_chat.models import DIRECT, FAMILY, ChatRoom, Message
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from tests.helpers import join_family, signup

MSG = "/family-chat/messages"
ROOMS = "/family-chat/rooms"
DIRECT_ROOM = "/family-chat/rooms/direct"
READ = "/family-chat/read"
STATES = "/family-chat/read-states"
UNREAD = "/family-chat/unread"


@pytest.fixture(autouse=True)
def _no_ai(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)


@pytest.fixture
def trio(client, family):
    """같은 가족 구성원 셋(지민 a, 수진 b, 삼촌 c)."""
    a, b, group = family
    c = signup(client, "삼촌")
    r = join_family(client, a, group["invite_code"], c)
    assert r.status_code == 200
    return a, b, c


def _uid(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def _direct(client, headers, peer_id):
    r = client.post(DIRECT_ROOM, json={"user_id": peer_id}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _send(client, headers, text="안녕", room_id=None):
    body = {"text": text} if room_id is None else {"text": text, "room_id": room_id}
    r = client.post(MSG, json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _texts(client, headers, room_id=None):
    params = {"latest": True, "limit": 50}
    if room_id:
        params["room_id"] = room_id
    r = client.get(MSG, params=params, headers=headers)
    assert r.status_code == 200, r.text
    return [m["text"] for m in r.json()]


def test_family_room_is_default_and_first(client, family):
    a, b, _ = family
    _send(client, a, "가족 모두에게")
    rooms = client.get(ROOMS, headers=b).json()
    assert [r["kind"] for r in rooms] == [FAMILY]
    assert rooms[0]["peer_user_id"] is None
    assert rooms[0]["last_message"]["text"] == "가족 모두에게"
    assert rooms[0]["unread"] == 1
    # room_id 없이 보낸 메시지는 가족 전체방에 연결된다
    with SessionLocal() as db:
        msg = db.scalars(select(Message)).one()
        assert msg.room_id == rooms[0]["id"]
    # 방 id 로 직접 불러도 같은 대화
    assert _texts(client, b, rooms[0]["id"]) == ["가족 모두에게"]


def test_legacy_message_without_room_is_in_family_room(client, family):
    a, _, _ = family
    uid = _uid(client, a)
    gid = client.get("/family-group/groups/me", headers=a).json()["id"]
    with SessionLocal() as db:  # 방 구조가 생기기 전(또는 배포 중 구 서버)이 쓴 메시지
        db.add(Message(group_id=gid, room_id=None, user_id=uid, text="옛 메시지"))
        db.commit()
    assert _texts(client, a) == ["옛 메시지"]


def test_open_direct_room_is_idempotent_for_both_sides(client, trio):
    a, b, c = trio
    uid_a, uid_b = _uid(client, a), _uid(client, b)
    first = _direct(client, a, uid_b)
    assert first["kind"] == DIRECT and first["peer_user_id"] == uid_b
    again = _direct(client, a, uid_b)
    assert again["id"] == first["id"]
    reverse = _direct(client, b, uid_a)
    assert reverse["id"] == first["id"] and reverse["peer_user_id"] == uid_a
    with SessionLocal() as db:
        assert len(db.scalars(select(ChatRoom).where(ChatRoom.kind == DIRECT)).all()) == 1
    # 다른 두 사람은 다른 방
    assert _direct(client, a, _uid(client, c))["id"] != first["id"]


def test_open_direct_rejects_self_non_member_and_other_family(client, trio, other_family):
    a, _, _ = trio
    assert client.post(DIRECT_ROOM, json={"user_id": _uid(client, a)}, headers=a).status_code == 400
    assert client.post(DIRECT_ROOM, json={"user_id": "nobody"}, headers=a).status_code == 400
    stranger = _uid(client, other_family)
    r = client.post(DIRECT_ROOM, json={"user_id": stranger}, headers=a)
    assert r.status_code == 400 and r.json()["code"] == "invalid_member"


def test_direct_messages_stay_in_their_room(client, trio):
    a, b, c = trio
    room = _direct(client, a, _uid(client, b))["id"]
    _send(client, a, "둘만 아는 얘기", room_id=room)
    _send(client, b, "알겠어", room_id=room)
    _send(client, a, "다 같이")
    assert _texts(client, a, room) == ["둘만 아는 얘기", "알겠어"]
    assert _texts(client, b, room) == ["둘만 아는 얘기", "알겠어"]
    assert _texts(client, a) == ["다 같이"]  # 가족 전체방에는 1:1 대화가 보이지 않는다
    assert _texts(client, c) == ["다 같이"]


def test_third_member_and_other_family_cannot_touch_direct_room(client, trio, other_family):
    a, b, c = trio
    room = _direct(client, a, _uid(client, b))["id"]
    m = _send(client, a, "비밀", room_id=room)
    for who in (c, other_family):
        assert client.get(MSG, params={"room_id": room}, headers=who).status_code == 404
        assert (
            client.post(MSG, json={"text": "끼어들기", "room_id": room}, headers=who).status_code
            == 404
        )
        assert (
            client.post(READ, json={"message_id": m, "room_id": room}, headers=who).status_code
            == 404
        )
        assert client.get(STATES, params={"room_id": room}, headers=who).status_code == 404
        assert client.get(UNREAD, params={"room_id": room}, headers=who).status_code == 404
    assert client.get(MSG, params={"room_id": "없는방"}, headers=a).status_code == 404
    # 삼촌의 방 목록에는 보이지 않는다
    assert [r["kind"] for r in client.get(ROOMS, headers=c).json()] == [FAMILY]


def test_read_and_unread_are_per_room(client, trio):
    a, b, _ = trio
    room = _direct(client, a, _uid(client, b))["id"]
    d1 = _send(client, a, "1:1 하나", room_id=room)
    f1 = _send(client, a, "가족 하나")
    assert client.get(UNREAD, params={"room_id": room}, headers=b).json()["unread"] == 1
    assert client.get(UNREAD, headers=b).json()["unread"] == 1
    # 1:1 방에서 읽어도 가족 전체방 안 읽은 수는 그대로
    client.post(READ, json={"message_id": d1, "room_id": room}, headers=b)
    assert client.get(UNREAD, params={"room_id": room}, headers=b).json() == {
        "unread": 0,
        "last_read_message_id": d1,
    }
    assert client.get(UNREAD, headers=b).json()["unread"] == 1
    # 다른 방의 메시지 id 로는 읽음 위치를 올릴 수 없다
    r = client.post(READ, json={"message_id": f1, "room_id": room}, headers=b)
    assert r.status_code == 400 and r.json()["code"] == "invalid_message"
    r = client.post(READ, json={"message_id": d1}, headers=b)
    assert r.status_code == 400


def test_direct_read_states_cover_both_members_only(client, trio):
    a, b, _ = trio
    uid_a, uid_b = _uid(client, a), _uid(client, b)
    room = _direct(client, a, uid_b)["id"]
    m = _send(client, a, "읽어줘", room_id=room)
    states = {
        s["user_id"]: s["last_read_message_id"]
        for s in client.get(STATES, params={"room_id": room}, headers=a).json()
    }
    assert states == {uid_a: m, uid_b: 0}  # 보낸 사람은 읽은 것으로, 상대는 아직
    client.post(READ, json={"message_id": m, "room_id": room}, headers=b)
    states = {
        s["user_id"]: s["last_read_message_id"]
        for s in client.get(STATES, params={"room_id": room}, headers=a).json()
    }
    assert states == {uid_a: m, uid_b: m}


def test_room_list_orders_by_recent_activity_with_unread(client, trio):
    a, b, c = trio
    uid_b, uid_c = _uid(client, b), _uid(client, c)
    room_b = _direct(client, a, uid_b)["id"]
    room_c = _direct(client, a, uid_c)["id"]
    _send(client, b, "수진 먼저", room_id=room_b)
    _send(client, c, "삼촌 나중", room_id=room_c)
    rooms = client.get(ROOMS, headers=a).json()
    assert [r["kind"] for r in rooms] == [FAMILY, DIRECT, DIRECT]
    assert [r["id"] for r in rooms[1:]] == [room_c, room_b]  # 최근 메시지 순
    assert rooms[1]["unread"] == 1 and rooms[1]["last_message"]["text"] == "삼촌 나중"
    assert rooms[1]["peer_user_id"] == uid_c


def test_direct_messages_are_not_sent_to_ai(client, trio):
    a, b, _ = trio
    room = _direct(client, a, _uid(client, b))["id"]
    _send(client, a, "비밀 이야기", room_id=room)
    _send(client, a, "가족 이야기")
    gid = client.get("/family-group/groups/me", headers=a).json()["id"]
    with SessionLocal() as db:
        rows = ai_repository.recent_messages(db, gid, 100)
    assert [m.text for m, _ in rows] == ["가족 이야기"]


def test_room_endpoints_require_login_and_group(client):
    assert client.get(ROOMS).status_code == 401
    assert client.post(DIRECT_ROOM, json={"user_id": "x"}).status_code == 401
    lonely = signup(client, "혼자")
    assert client.get(ROOMS, headers=lonely).status_code in (400, 403, 404)


def test_late_joiner_baseline_ignores_direct_room_messages(client, trio):
    a, b, group = trio[0], trio[1], None
    group = client.get("/family-group/groups/me", headers=a).json()
    family_msg = _send(client, a, "가족 메시지")
    room = _direct(client, a, _uid(client, b))["id"]
    for i in range(3):
        _send(client, a, f"둘만 {i}", room_id=room)  # 가족 메시지보다 id 가 큰 1:1 메시지
    d = signup(client, "이모")
    r = join_family(client, a, group["invite_code"], d)
    assert r.status_code == 200
    got = client.get(UNREAD, headers=d).json()
    assert got == {"unread": 0, "last_read_message_id": family_msg}  # 1:1 메시지 id 가 아니다
    states = {s["user_id"]: s["last_read_message_id"] for s in client.get(STATES, headers=a).json()}
    assert states[_uid(client, d)] == family_msg


def test_room_creation_race_returns_existing_room(client, trio, monkeypatch):
    from app.features.family_chat import repository as chat_repo

    a, b, _ = trio
    uid_b = _uid(client, b)
    first = _direct(client, a, uid_b)
    # 다른 요청이 먼저 만든 것처럼: 처음 조회에서는 없다고 보이고 insert 가 유니크 충돌한다
    real = chat_repo.get_direct_room
    calls = {"n": 0}

    def stale_first(db, group_id, key):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(db, group_id, key)

    monkeypatch.setattr(chat_repo, "get_direct_room", stale_first)
    again = _direct(client, a, uid_b)
    assert again["id"] == first["id"]
    with SessionLocal() as db:
        assert len(db.scalars(select(ChatRoom).where(ChatRoom.kind == DIRECT)).all()) == 1


def test_family_room_creation_race_returns_existing_room(client, family):
    from app.features.family_chat import repository as chat_repo

    a, _, _ = family
    first = client.get(ROOMS, headers=a).json()[0]["id"]
    gid = client.get("/family-group/groups/me", headers=a).json()["id"]
    with SessionLocal() as db:
        real_scalar = db.scalar
        calls = {"n": 0}

        def stale_first(stmt, *args, **kwargs):
            calls["n"] += 1
            return None if calls["n"] == 1 else real_scalar(stmt, *args, **kwargs)

        # 다른 요청이 먼저 만든 것처럼: 처음 조회에서는 없다고 보이고 insert 가 유니크 충돌한다
        db.scalar = stale_first
        assert chat_repo.get_family_room(db, gid).id == first
    with SessionLocal() as db:
        assert len(db.scalars(select(ChatRoom).where(ChatRoom.kind == FAMILY)).all()) == 1


def test_room_list_query_count_does_not_grow_with_rooms(client, trio):
    from sqlalchemy import event

    from app.shared.db import engine

    a, b, c = trio

    def count_queries():
        n = {"v": 0}

        def on_exec(*args, **kwargs):
            n["v"] += 1

        event.listen(engine, "before_cursor_execute", on_exec)
        try:
            assert client.get(ROOMS, headers=a).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", on_exec)
        return n["v"]

    _direct(client, a, _uid(client, b))
    count_queries()  # 처음 한 번은 가족 전체방을 만들 수 있어 제외
    one = count_queries()
    _direct(client, a, _uid(client, c))
    two = count_queries()
    assert two == one  # 1:1 방이 늘어도 쿼리 수는 같다
