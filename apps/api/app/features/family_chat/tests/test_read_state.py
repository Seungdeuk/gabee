"""가족 대화 읽음 상태: 안 읽은 수, 읽음 위치(단조 증가), 구성원별 읽음 목록."""

import httpx
import pytest

from app.features.family_chat import repository as chat_repo
from app.features.family_chat.models import ChatRoomRead
from app.features.family_group.models import GroupMember
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from tests.helpers import signup

MSG = "/family-chat/messages"
READ = "/family-chat/read"
STATES = "/family-chat/read-states"
UNREAD = "/family-chat/unread"


@pytest.fixture(autouse=True)
def _no_ai(monkeypatch):
    """읽음 처리와 일반 메시지 전송은 AI 를 부르지 않는다."""

    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)


def _send(client, headers, text="안녕"):
    r = client.post(MSG, json={"text": text}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _user_id(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def test_unread_read_flow(client, family):
    a, b, _ = family
    assert client.get(UNREAD, headers=b).json() == {"unread": 0, "last_read_message_id": 0}
    m1 = _send(client, a, "하나")
    m2 = _send(client, a, "둘")
    assert client.get(UNREAD, headers=b).json() == {"unread": 2, "last_read_message_id": 0}
    r = client.post(READ, json={"message_id": m1}, headers=b)
    assert r.status_code == 200
    assert r.json() == {"last_read_message_id": m1}
    assert client.get(UNREAD, headers=b).json() == {"unread": 1, "last_read_message_id": m1}
    client.post(READ, json={"message_id": m2}, headers=b)
    assert client.get(UNREAD, headers=b).json() == {"unread": 0, "last_read_message_id": m2}


def test_read_position_only_moves_forward(client, family):
    a, b, _ = family
    m1 = _send(client, a)
    m2 = _send(client, a)
    client.post(READ, json={"message_id": m2}, headers=b)
    r = client.post(READ, json={"message_id": m1}, headers=b)
    assert r.status_code == 200
    assert r.json() == {"last_read_message_id": m2}
    assert client.get(UNREAD, headers=b).json()["last_read_message_id"] == m2
    # 같은 값 반복도 그대로
    assert client.post(READ, json={"message_id": m2}, headers=b).json() == {
        "last_read_message_id": m2
    }


def test_own_messages_are_not_unread_and_sending_marks_read(client, family):
    a, b, _ = family
    m1 = _send(client, a)
    m2 = _send(client, b, "답장")  # b 가 보냄: b 의 읽음 위치가 m2 로 올라간다
    assert client.get(UNREAD, headers=b).json() == {"unread": 0, "last_read_message_id": m2}
    assert client.get(UNREAD, headers=a).json() == {"unread": 1, "last_read_message_id": m1}
    states = {s["user_id"]: s["last_read_message_id"] for s in client.get(STATES, headers=a).json()}
    assert states[_user_id(client, a)] == m1
    assert states[_user_id(client, b)] == m2


def test_read_rejects_message_of_other_group_and_unknown(client, family, other_family):
    a, b, _ = family
    foreign = _send(client, other_family, "남의 가족 메시지")
    mine = _send(client, a)
    for bad in (foreign, mine + 1000):
        r = client.post(READ, json={"message_id": bad}, headers=b)
        assert r.status_code == 400
        assert r.json()["code"] == "invalid_message"
    # 거절된 요청은 위치를 만들지 않는다
    assert client.get(UNREAD, headers=b).json()["last_read_message_id"] == 0
    assert client.post(READ, json={"message_id": 0}, headers=b).status_code == 422


def test_read_states_members_only_with_default_zero(client, family, other_family):
    a, b, _ = family
    m1 = _send(client, a)
    client.post(READ, json={"message_id": m1}, headers=b)
    c = signup(client, "민수")  # 그룹에 없는 사람
    uid_a, uid_b = _user_id(client, a), _user_id(client, b)
    out = client.get(STATES, headers=a).json()
    assert {s["user_id"] for s in out} == {uid_a, uid_b}
    # 다른 가족 구성원은 안 보인다
    assert _user_id(client, other_family) not in {s["user_id"] for s in out}
    assert _user_id(client, c) not in {s["user_id"] for s in out}

    # 탈퇴(구성원 행 삭제)한 사람은 목록에서 빠진다. 읽음 기록이 남아 있어도 마찬가지다.
    with SessionLocal() as db:
        db.query(GroupMember).filter(GroupMember.user_id == uid_b).delete()
        db.commit()
    out = client.get(STATES, headers=a).json()
    assert [s["user_id"] for s in out] == [uid_a]
    assert out[0]["last_read_message_id"] == m1


def test_read_states_default_zero_for_member_without_record(client, family):
    a, b, _ = family
    out = client.get(STATES, headers=a).json()
    assert {s["last_read_message_id"] for s in out} == {0}
    assert len(out) == 2
    assert out[0]["user_id"] == _user_id(client, a)


def test_families_are_isolated(client, family, other_family):
    a, b, _ = family
    m1 = _send(client, a)
    _send(client, other_family, "다른 가족")
    assert client.get(UNREAD, headers=b).json()["unread"] == 1
    assert client.get(UNREAD, headers=other_family).json()["unread"] == 0
    client.post(READ, json={"message_id": m1}, headers=b)
    states = client.get(STATES, headers=other_family).json()
    assert [s["user_id"] for s in states] == [_user_id(client, other_family)]
    assert states[0]["last_read_message_id"] != m1


def test_requires_login_and_group(client):
    for method, url in (("get", UNREAD), ("get", STATES)):
        assert getattr(client, method)(url).status_code == 401
    assert client.post(READ, json={"message_id": 1}).status_code == 401
    lone = signup(client, "혼자")  # 가족 그룹 없음
    for r in (
        client.get(UNREAD, headers=lone),
        client.get(STATES, headers=lone),
        client.post(READ, json={"message_id": 1}, headers=lone),
    ):
        assert r.status_code == 400
        assert r.json()["code"] == "no_group"


def test_first_save_primary_key_conflict_is_handled(client, family, monkeypatch):
    a, b, _ = family
    m1 = _send(client, a)
    m2 = _send(client, a)
    client.post(READ, json={"message_id": m1}, headers=b)  # b 의 행이 이미 있다

    real = chat_repo._get_state
    calls = {"n": 0}

    def stale_first(db, group_id, user_id):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(db, group_id, user_id)

    # 다른 요청이 먼저 행을 만든 것처럼: 처음엔 없다고 보고 insert 하다가 키 충돌이 난다
    monkeypatch.setattr(chat_repo, "_get_state", stale_first)
    r = client.post(READ, json={"message_id": m2}, headers=b)
    assert r.status_code == 200, r.text
    assert r.json() == {"last_read_message_id": m2}
    with SessionLocal() as db:
        rows = db.query(ChatRoomRead).all()
        assert sorted(x.last_read_message_id for x in rows if x.user_id != _user_id(client, a)) == [
            m2
        ]


def test_conflict_does_not_lower_position(client, family, monkeypatch):
    a, b, _ = family
    m1 = _send(client, a)
    m2 = _send(client, a)
    client.post(READ, json={"message_id": m2}, headers=b)
    monkeypatch.setattr(chat_repo, "_get_state", lambda db, g, u: None)
    r = client.post(READ, json={"message_id": m1}, headers=b)
    assert r.status_code == 200
    assert r.json() == {"last_read_message_id": m2}


def test_unread_is_capped(client, family, monkeypatch):
    a, b, _ = family
    monkeypatch.setattr(chat_repo, "UNREAD_CAP", 5)
    for i in range(7):
        _send(client, a, f"메시지 {i}")
    assert client.get(UNREAD, headers=b).json()["unread"] == 5


def test_late_joiner_baseline_is_join_time(client, family):
    a, b, group = family
    for i in range(30):
        _send(client, a, f"옛 메시지 {i}")
    c = signup(client, "삼촌")
    assert (
        client.post(
            "/family-group/groups/join", json={"code": group["invite_code"]}, headers=c
        ).status_code
        == 200
    )
    uid_c = _user_id(client, c)
    got = client.get(UNREAD, headers=c).json()
    assert got["unread"] == 0 and got["last_read_message_id"] > 0
    base = got["last_read_message_id"]
    # 기존 구성원이 보면 삼촌의 위치는 합류 시점 기준선이라 옛 메시지가 새로 '안 읽음'이 되지 않는다
    states = {s["user_id"]: s["last_read_message_id"] for s in client.get(STATES, headers=a).json()}
    assert states[uid_c] == base
    # 이후 새 메시지만 늘어난다
    new1 = _send(client, a, "새 메시지")
    _send(client, b, "또 새 메시지")
    got = client.get(UNREAD, headers=c).json()
    assert got == {"unread": 2, "last_read_message_id": base}
    assert new1 > base
    # 기록이 있으면 기록과 기준선 중 큰 값
    client.post(READ, json={"message_id": new1}, headers=c)
    assert client.get(UNREAD, headers=c).json() == {"unread": 1, "last_read_message_id": new1}


def test_read_rejects_out_of_range_message_id(client, family):
    _, b, _ = family
    r = client.post(READ, json={"message_id": 2**33}, headers=b)
    assert r.status_code == 422
