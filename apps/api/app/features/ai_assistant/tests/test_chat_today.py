"""메인 채팅 모델에게 오늘 날짜를 알려 주는지 확인한다. 실제 모델은 부르지 않고 요청 본문만 본다."""

from datetime import UTC, datetime

from app.features.ai_assistant.knowledge import rag_chat
from app.shared.config import settings
from tests.ai_consent import enable_ai


def test_today_note_uses_service_timezone_and_weekday(monkeypatch):
    monkeypatch.setattr(settings, "ai_day_utc_offset_hours", 9)
    # UTC 로는 10-25 23:30 이지만 한국 시간으로는 10-26(월) 08:30
    now = datetime(2026, 10, 25, 23, 30, tzinfo=UTC)
    note = rag_chat.today_note(now)
    assert "오늘은 2026-10-26(월요일)입니다." in note


def test_system_prompt_contains_today_for_both_modes():
    now = datetime(2026, 10, 26, 3, 0, tzinfo=UTC)
    for with_agents in (False, True):
        assert "오늘은 2026-10-26(월요일)" in rag_chat.system_prompt(with_agents, now)


def test_chat_request_carries_today(client, family, monkeypatch):
    a, _, group = family
    enable_ai(group["id"])
    seen = []

    def fake_post(body):
        seen.append(body["system"])
        return {"content": [{"type": "text", "text": "안녕하세요"}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    client.post("/ai-assistant/chat", json={"message": "안녕"}, headers=a)
    today = rag_chat.today_note()
    assert seen and today in seen[0]
