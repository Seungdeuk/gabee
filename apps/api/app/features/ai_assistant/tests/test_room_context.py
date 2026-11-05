"""방에서 @가비 를 부르면 그 방의 최근 대화(최근 10개, 30분 이내)를 개인정보를 가린 채 맥락으로 함께 보낸다.
"일정 잡아줘"만 써도 직전의 "낚시 가자"를 알아듣게 하려는 것이다. 개인 대화(audience=me)에는 붙이지 않는다."""

# 다른 시험 파일의 fixture(trio)를 가져다 쓴다(pytest 방식이라 F811 은 무시한다)
# ruff: noqa: F811
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.features.ai_assistant.knowledge import rag_chat
from app.features.family_chat.models import Message
from app.features.family_chat.tests.test_rooms import _direct, _send, _uid, trio  # noqa: F401
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.ai_consent import enable_ai

MSG = "/family-chat/messages"
CONTEXT_MARK = "방의 최근 대화"


@pytest.fixture
def setup(client, trio, monkeypatch):
    a, b, c = trio
    group_id = client.get("/family-group/me", headers=a).json()["active_group_id"]
    enable_ai(group_id)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    systems = []

    def fake_post(req):
        systems.append(req["system"])
        return {"content": [{"type": "text", "text": "답이에요"}]}

    monkeypatch.setattr(rag_chat, "_post", fake_post)
    return a, b, c, systems


def _say(client, headers, text, room_id=None):
    body = {"text": text} if room_id is None else {"text": text, "room_id": room_id}
    assert client.post(MSG, json=body, headers=headers).status_code == 201


def _ask(client, headers, message="일정 잡아줘", **body):
    r = client.post(
        "/ai-assistant/chat", json={"message": message, "audience": "room", **body}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


def _age_all(minutes):
    with SessionLocal() as db:
        db.execute(
            update(Message).values(created_at=datetime.now(UTC) - timedelta(minutes=minutes))
        )
        db.commit()


def test_recent_room_chat_is_sent_as_context(client, setup):
    a, b, _, systems = setup
    _say(client, b, "토요일에 낚시 가자")
    _ask(client, a)
    assert CONTEXT_MARK in systems[-1] and "토요일에 낚시 가자" in systems[-1]


def test_only_last_ten_messages_are_sent(client, setup):
    a, b, _, systems = setup
    for i in range(12):
        _say(client, a if i % 2 else b, f"이야기{i:02d}")
    _ask(client, a)
    sent = systems[-1]
    assert "이야기11" in sent and "이야기02" in sent  # 마지막 10개(02~11)
    assert "이야기01" not in sent and "이야기00" not in sent


def test_messages_older_than_thirty_minutes_are_not_sent(client, setup):
    a, b, _, systems = setup
    _say(client, b, "옛날 낚시 이야기")
    _age_all(31)
    _say(client, b, "방금 한 이야기")
    _ask(client, a)
    assert "방금 한 이야기" in systems[-1] and "옛날 낚시 이야기" not in systems[-1]


def test_context_is_masked_and_names_are_pseudonymized(client, setup):
    a, b, _, systems = setup
    _say(client, b, "수진 계좌는 110-222-333444 이고 전화는 010-1234-5678 이야")
    _ask(client, a)
    sent = systems[-1]
    assert CONTEXT_MARK in sent
    assert "110-222-333444" not in sent and "010-1234-5678" not in sent
    assert "수진" not in sent.split(CONTEXT_MARK, 1)[1]  # 이름도 토큰으로 바뀌어 나간다


def test_personal_chat_never_gets_room_context(client, setup):
    a, b, _, systems = setup
    _say(client, b, "토요일에 낚시 가자")
    r = client.post("/ai-assistant/chat", json={"message": "일정 잡아줘"}, headers=a)
    assert r.status_code == 200
    assert CONTEXT_MARK not in systems[-1] and "낚시" not in systems[-1]


def test_direct_room_uses_only_that_room(client, setup):
    a, b, c, systems = setup
    direct = _direct(client, a, _uid(client, b))
    other = _direct(client, a, _uid(client, c))
    _say(client, a, "가족방 낚시 이야기")
    _say(client, b, "둘만의 낚시 이야기", direct["id"])
    _say(client, c, "셋째와의 낚시 이야기", other["id"])
    _ask(client, a, room_id=direct["id"])
    sent = systems[-1]
    assert "둘만의 낚시 이야기" in sent
    assert "가족방 낚시 이야기" not in sent and "셋째와의 낚시 이야기" not in sent


def test_no_recent_messages_means_no_context_block(client, setup):
    a, b, _, systems = setup
    _say(client, b, "아주 오래된 이야기")
    _age_all(120)
    _ask(client, a)
    assert CONTEXT_MARK not in systems[-1]


def test_blocked_sensitive_messages_stay_out(client, setup):
    a, b, _, systems = setup
    _say(client, b, "비밀번호는 zebra-7788-pw 이야")
    _ask(client, a)
    assert "zebra-7788-pw" not in systems[-1]


def test_blocked_message_shows_up_masked_not_raw(client, setup):
    a, b, _, systems = setup
    _say(client, b, "비밀번호는 zebra-7788-pw 이야")
    _ask(client, a)
    sent = systems[-1]
    assert CONTEXT_MARK in sent and "zebra-7788-pw" not in sent


def test_context_has_its_own_small_size_cap(client, setup):
    a, b, _, systems = setup
    for i in range(10):
        _say(client, a if i % 2 else b, f"낚시터 {i:02d} " + "가나다라마바사 " * 100)
    _ask(client, a)
    block = systems[-1].split(CONTEXT_MARK, 1)[1]
    assert 0 < len(block) < 3600


def test_names_from_the_room_are_not_restored_for_billing_agent(client, setup, monkeypatch):
    import re

    a, b, _, _ = setup
    _say(client, b, "수진이 학원비 30만원 보냈어")
    seen = {}

    def fake_post(req):
        if "가계(정산) 담당" in req["system"]:
            seen["billing_question"] = str(req["messages"][0]["content"])
            return {"content": [{"type": "text", "text": "정산 답"}]}
        if len(req["messages"]) == 1:
            token = re.search(r"\[PERSON_\d+\]", req["system"]).group(0)
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "ask_billing",
                        "input": {"question": f"{token} 학원비 30만원 정산"},
                    }
                ]
            }
        return {"content": [{"type": "text", "text": "끝"}]}

    monkeypatch.setattr(rag_chat, "_post", fake_post)
    _ask(client, a, "이거 정산해줘")
    assert (
        "수진" not in seen["billing_question"]
    )  # 남이 쓴 글의 이름은 정산 에이전트의 모델 호출로 나가지 않는다


def test_final_answer_tokens_are_restored(client, setup, monkeypatch):
    import re

    a, b, _, _ = setup
    _say(client, b, "수진이 낚시 가자")

    def fake_post(req):
        token = re.search(r"\[PERSON_\d+\]", req["system"]).group(0)
        return {"content": [{"type": "text", "text": f"{token} 낚시 일정이에요"}]}

    monkeypatch.setattr(rag_chat, "_post", fake_post)
    out = _ask(client, a, "누구 얘기야")
    assert "[PERSON_" not in out["reply"]


def test_context_is_not_built_when_ai_is_off(client, setup, monkeypatch):
    from app.features.family_chat import assistant

    a, b, _, _ = setup
    _say(client, b, "토요일에 낚시 가자")
    assert (
        client.put("/family-chat/ai/settings", json={"enabled": False}, headers=a).status_code
        == 200
    )
    built = []
    monkeypatch.setattr(assistant, "room_context", lambda *args, **kw: built.append(1))
    r = client.post(
        "/ai-assistant/chat", json={"message": "일정 잡아줘", "audience": "room"}, headers=a
    )
    assert r.status_code in (200, 403)
    assert built == []  # 동의가 꺼진 가족의 대화는 가명화하지 않는다


def test_context_is_closed_even_when_the_model_fails(client, setup, monkeypatch):
    import httpx

    from app.features.family_chat import ai_service

    a, b, _, _ = setup
    _say(client, b, "토요일에 낚시 가자")
    closed = []
    real_close = ai_service._Context.close
    monkeypatch.setattr(
        ai_service._Context, "close", lambda self: (closed.append(1), real_close(self))[1]
    )

    def boom(req):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(rag_chat, "_post", boom)
    client.post(
        "/ai-assistant/chat", json={"message": "일정 잡아줘", "audience": "room"}, headers=a
    )
    assert closed == [1]


def test_gabi_previous_answers_are_in_context_and_told_not_to_redo(client, setup):
    a, b, _, systems = setup
    _say(client, b, "토요일에 낚시 가자")
    _ask(client, a, "일정 잡아줘")  # 가비가 방에 "답이에요"를 올린다
    _ask(client, a, "그중 식비는?")
    sent = systems[-1]
    assert "답이에요" in sent.split(CONTEXT_MARK, 1)[1]  # 가비가 이미 한 말도 맥락에 있다
    assert "다시 실행" in sent  # 이전 요청(일정 등록 등)을 다시 하지 않는다
