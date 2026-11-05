"""1:1 방에서 @가비 로 부른 답은 그 1:1 방에 가비 이름으로 저장해 두 사람에게만 보인다(room_id). 참가자가 아니거나 상대가
가족을 나갔으면 AI 를 부르지 않고 막는다. 1:1 에서는 일정 에이전트를 아직 쓰지 않는다(상대 기준 공유는 별도 작업)."""

# 다른 시험 파일의 fixture(trio)를 가져다 쓴다(pytest 방식이라 F811 은 무시한다)
# ruff: noqa: F811
import pytest

from app.features.ai_assistant import agents
from app.features.ai_assistant.knowledge import rag_chat
from app.features.family_chat.models import ASSISTANT_NAME
from app.features.family_chat.tests.test_rooms import _direct, _send, _uid, trio  # noqa: F401
from app.features.family_group.models import User
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.ai_consent import enable_ai

MSG = "/family-chat/messages"
LEAVE = "/family-group/groups/me/leave"


@pytest.fixture
def setup(client, trio, monkeypatch):
    """AI 를 켠 가족(지민 a, 수진 b, 삼촌 c)과 a-b 1:1 방. 가짜 AI 호출 횟수를 센다."""
    a, b, c = trio
    group_id = client.get("/family-group/me", headers=a).json()["active_group_id"]
    enable_ai(group_id)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    direct = _direct(client, a, _uid(client, b))
    calls = []

    def fake_post(req):
        calls.append(req)
        return {"content": [{"type": "text", "text": "둘에게 보이는 답"}]}

    monkeypatch.setattr(rag_chat, "_post", fake_post)
    return a, b, c, direct, calls


def _ask(client, headers, **body):
    return client.post(
        "/ai-assistant/chat", json={"message": "질문", "audience": "room", **body}, headers=headers
    )


def _texts(client, headers, room_id=None):
    params = {"latest": True, "limit": 50}
    if room_id:
        params["room_id"] = room_id
    r = client.get(MSG, params=params, headers=headers)
    assert r.status_code == 200, r.text
    return [m["text"] for m in r.json()]


def test_answer_is_posted_to_the_direct_room_only(client, setup):
    a, b, c, direct, calls = setup
    r = _ask(client, a, room_id=direct["id"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["visibility"] == "room" and out["posted_message_id"] is not None
    for headers in (a, b):  # 1:1 두 사람은 그 방에서 가비의 답을 본다
        msgs = client.get(
            MSG, params={"latest": True, "limit": 50, "room_id": direct["id"]}, headers=headers
        ).json()
        assert [m["text"] for m in msgs] == [out["reply"]]
        assert msgs[0]["user_name"] == ASSISTANT_NAME and msgs[0]["is_assistant"] is True
    assert _texts(client, a) == []  # 가족 전체방에는 올라가지 않는다
    assert _texts(client, c) == []


def test_third_member_cannot_read_or_use_the_direct_room(client, setup):
    a, b, c, direct, calls = setup
    _ask(client, a, room_id=direct["id"])
    r = client.get(MSG, params={"latest": True, "limit": 50, "room_id": direct["id"]}, headers=c)
    assert r.status_code in (403, 404)
    before = len(calls)
    r = _ask(client, c, room_id=direct["id"])
    assert r.status_code == 404
    assert len(calls) == before  # AI 를 부르지 않았다


def test_unknown_room_is_not_found_without_calling_ai(client, setup):
    a, _, _, _, calls = setup
    assert _ask(client, a, room_id="nope").status_code == 404
    assert calls == []


def test_blocked_when_the_other_person_left(client, setup):
    a, b, _, direct, calls = setup
    assert client.post(LEAVE, headers=b).status_code in (200, 204)
    r = _ask(client, a, room_id=direct["id"])
    assert r.status_code == 403 and r.json()["code"] == "peer_left"
    assert calls == []
    assert _ask(client, a).status_code == 200  # 가족 전체방 @가비 는 그대로


def test_room_id_is_ignored_for_personal_chat(client, setup):
    a, _, _, direct, _ = setup
    r = client.post(
        "/ai-assistant/chat", json={"message": "질문", "room_id": direct["id"]}, headers=a
    )
    assert r.status_code == 200, r.text
    assert r.json()["posted_message_id"] is None  # audience=me 는 방에 올리지 않는다
    assert _texts(client, a, direct["id"]) == []


def test_schedule_agent_is_not_used_in_direct_rooms_yet(client, setup):
    a, _, _, _, _ = setup
    with SessionLocal() as db:
        user = db.get(User, _uid(client, a))
        result, _, _, _ = agents.call(
            db,
            user.active_group_id,
            user,
            "ask_schedule",
            {"question": "내 일정 알려줘"},
            None,
            audience="direct",
        )
    assert result["can_answer"] is False


def test_schedule_tool_call_through_the_endpoint_gives_no_cards_in_direct_room(
    client, setup, monkeypatch
):
    a, _, _, direct, _ = setup

    def fake_post(req):
        if len(req["messages"]) == 1:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "ask_schedule",
                        "input": {"question": "토요일 일정 넣어줘"},
                    }
                ]
            }
        return {"content": [{"type": "text", "text": "일정은 아직 다루지 않아요"}]}

    monkeypatch.setattr(rag_chat, "_post", fake_post)
    out = _ask(client, a, room_id=direct["id"]).json()
    assert out["confirm_cards"] == [] and out["proposals"] == []


def test_fallback_answer_is_not_posted_to_direct_room(client, setup, monkeypatch):
    a, _, _, direct, _ = setup
    monkeypatch.setattr(settings, "anthropic_api_key", "")  # AI 를 못 써서 기록 검색 결과만 나온다
    out = _ask(client, a, room_id=direct["id"]).json()
    assert out["visibility"] == "private" and out["posted_message_id"] is None
    assert _texts(client, a, direct["id"]) == []


def test_family_room_id_posts_to_the_family_room(client, setup):
    a, b, _, direct, _ = setup
    rooms = client.get("/family-chat/rooms", headers=a).json()
    family_room = next(r for r in rooms if r["kind"] == "family")
    out = _ask(client, a, room_id=family_room["id"]).json()
    assert out["posted_message_id"] is not None
    assert _texts(client, b) == [out["reply"]]
    assert _texts(client, a, direct["id"]) == []


def test_other_family_cannot_use_the_direct_room(client, setup, other_family):
    _, _, _, direct, calls = setup
    assert _ask(client, other_family, room_id=direct["id"]).status_code == 404
    assert calls == []
