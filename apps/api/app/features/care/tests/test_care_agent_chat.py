"""돌봄 에이전트와 직접 대화(POST /care/agent/chat). 실제 LLM 은 부르지 않고 가짜 LLM 을 끼운다."""

import json

from app.shared.config import settings
from app.shared.llm import agent
from tests.ai_consent import enable_ai_for_user


def test_agent_chat_reads_daily_and_only_has_care_tools(client, family, monkeypatch):
    a, _, _ = family
    daily = client.get("/care/daily", params={"date": "2026-10-20"}, headers=a).json()
    name = daily["items"][0]["name"]
    seen = []

    def fake(body):
        seen.append(body)
        last = body["messages"][-1]
        if isinstance(last["content"], str):
            call = {"type": "tool_use", "id": "t", "name": "get_daily"}
            return {"content": [{**call, "input": {"date": "2026-10-20"}}]}
        data = json.dumps(json.loads(last["content"][0]["content"]), ensure_ascii=False)
        return {"content": [{"type": "text", "text": name if name in data else "없음"}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(agent, "_post", fake)
    enable_ai_for_user()
    r = client.post("/care/agent/chat", json={"message": "20일 돌봄 항목은?"}, headers=a).json()
    assert r["source"] == "ai" and r["reply"] == name and r["tool_calls"] == ["get_daily"]
    names = [t["name"] for t in seen[0]["tools"]]
    assert "get_month_summary" not in names  # 정산 도구는 없다
    for gone in (
        "get_recommendations",
        "get_meal_suggestions",
        "list_meal_log",
        "get_meal_log_summary",
    ):
        assert gone not in names  # 화면에서 뺀 추천·식단 도구는 주지 않는다


def test_agent_chat_without_api_key_falls_back(client, family):
    a, _, _ = family
    r = client.post("/care/agent/chat", json={"message": "오늘은?"}, headers=a).json()
    assert r["source"] == "fallback" and r["tool_calls"] == []
