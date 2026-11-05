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
