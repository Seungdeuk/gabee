"""1:1 방에서도 AI 도우미(분석·답장·주제·미리보기)를 쓴다: room_id 를 주면 그 1:1 방 대화만 읽고, 참가자가 아니면 거부하고,
상대가 가족을 나갔으면 쓸 수 없다. room_id 가 없으면 예전처럼 가족 전체방만 읽는다. 실제 Anthropic 은 부르지 않는다."""

# 다른 시험 파일의 fixture(fake·trio)를 가져다 쓰고, 시험 함수 인자로 받는다(pytest 방식이라 F811 은 무시한다)
# ruff: noqa: F811
import pytest

from .test_ai_analysis import AI, analyze, enable, fake, say  # noqa: F401  (fake 는 fixture)
from .test_rooms import _direct, _send, _uid, trio  # noqa: F401  (trio 는 fixture)

LEAVE = "/family-group/groups/me/leave"


@pytest.fixture
def chats(client, trio, fake):  # noqa: F811
    """AI 를 켜고, 가족방 대화 3건과 지민(a)-수진(b) 1:1 방 대화 3건이 있는 가족. (a, b, c, 1:1 방)."""
    a, b, c = trio
    enable(client, a)
    direct = _direct(client, a, _uid(client, b))
    for i in range(3):
        say(client, a if i % 2 == 0 else b, f"가족방 이야기 {i}")
        _send(client, a if i % 2 == 0 else b, f"둘만의 이야기 {i}", room_id=direct["id"])
    return a, b, c, direct


def _leave(client, headers):
    r = client.post(LEAVE, headers=headers)
    assert r.status_code in (200, 204), r.text


def test_direct_analysis_reads_only_that_room(client, chats, fake):
    a, _, _, direct = chats
    r = analyze(client, a, room_id=direct["id"])
    assert r.status_code == 200, r.text
    prompt = fake.calls[-1]["prompt"]
    assert "둘만의 이야기" in prompt and "가족방 이야기" not in prompt
    analyze(client, a)  # room_id 가 없으면 예전처럼 가족 전체방만 읽는다(1:1 글은 안 읽음)
    prompt = fake.calls[-1]["prompt"]
    assert "가족방 이야기" in prompt and "둘만의 이야기" not in prompt


@pytest.mark.parametrize("path", ["analysis", "replies", "topics"])
def test_direct_replies_and_topics_are_scoped_too(client, chats, fake, path):
    a, _, _, direct = chats
    r = client.post(f"{AI}/{path}", json={"room_id": direct["id"]}, headers=a)
    assert r.status_code == 200, r.text
    prompt = fake.calls[-1]["prompt"]
    assert "둘만의 이야기" in prompt and "가족방 이야기" not in prompt


def test_direct_preview_shows_only_that_room(client, chats):
    a, _, _, direct = chats
    r = client.post(f"{AI}/preview", json={"room_id": direct["id"]}, headers=a)
    assert r.status_code == 200, r.text
    assert "둘만의 이야기" in r.text and "가족방 이야기" not in r.text


def test_both_participants_can_use_it_but_a_third_member_cannot(client, chats, fake):
    a, b, c, direct = chats
    assert analyze(client, b, room_id=direct["id"]).status_code == 200  # 참가자 둘 다
    calls = len(fake.calls)
    for path in ("analysis", "replies", "topics", "preview"):
        r = client.post(f"{AI}/{path}", json={"room_id": direct["id"]}, headers=c)
        assert r.status_code == 404, (path, r.text)  # 방이 있는지도 드러내지 않는다
    assert len(fake.calls) == calls  # AI 를 부르지 않았다


def test_unknown_room_and_other_family_room_are_not_found(client, chats, other_family, fake):
    a, _, _, direct = chats
    assert analyze(client, a, room_id="nope").status_code == 404
    assert analyze(client, other_family, room_id=direct["id"]).status_code == 404  # 다른 가족의 방


def test_family_room_id_works_like_no_room_id(client, chats, fake):
    a, _, _, _ = chats
    rooms = client.get("/family-chat/rooms", headers=a).json()
    family_room = next(r for r in rooms if r["kind"] == "family")
    assert analyze(client, a, room_id=family_room["id"]).status_code == 200
    assert "둘만의 이야기" not in fake.calls[-1]["prompt"]


@pytest.mark.parametrize("path", ["analysis", "replies", "topics", "preview"])
def test_ai_is_blocked_when_the_other_person_left_the_family(client, chats, fake, path):
    a, b, _, direct = chats
    _leave(client, b)  # 상대가 가족을 나갔다
    calls = len(fake.calls)
    r = client.post(f"{AI}/{path}", json={"room_id": direct["id"]}, headers=a)
    assert r.status_code == 403 and r.json()["code"] == "peer_left", (path, r.text)
    assert len(fake.calls) == calls  # AI 를 부르지 않았고 한도도 쓰지 않았다
    assert analyze(client, a).status_code == 200  # 가족 전체방은 그대로 쓴다


def test_each_room_has_its_own_cached_result(client, chats, fake):
    a, b, _, direct = chats
    analyze(client, a, room_id=direct["id"])
    analyze(client, a)  # 같은 사람·같은 날이어도 방이 다르면 다른 결과(다른 메시지)
    assert len(fake.calls) == 2
    analyze(client, a, room_id=direct["id"])  # 같은 사람의 같은 1:1 방·같은 범위는 캐시를 쓴다
    assert len(fake.calls) == 2
    analyze(
        client, b, room_id=direct["id"]
    )  # 같은 방이어도 다른 참가자는 자기 입장의 결과를 새로 만든다
    assert len(fake.calls) == 3


def test_another_direct_room_of_mine_is_not_mixed_in(client, chats, trio, fake):
    a, _, c, direct = chats
    other = _direct(client, a, _uid(client, c))  # a-c 방
    for i in range(3):
        _send(client, a if i % 2 == 0 else c, f"셋째와의 이야기 {i}", room_id=other["id"])
    analyze(client, a, room_id=direct["id"])
    prompt = fake.calls[-1]["prompt"]
    assert "둘만의 이야기" in prompt and "셋째와의 이야기" not in prompt
    analyze(client, a, room_id=other["id"])
    prompt = fake.calls[-1]["prompt"]
    assert "셋째와의 이야기" in prompt and "둘만의 이야기" not in prompt


def test_rejected_requests_never_call_ai(client, chats, other_family, fake):
    a, _, _, direct = chats
    calls = len(fake.calls)
    assert analyze(client, a, room_id="nope").status_code == 404
    assert analyze(client, other_family, room_id=direct["id"]).status_code == 404
    assert len(fake.calls) == calls
