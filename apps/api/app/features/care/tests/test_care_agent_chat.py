"""돌봄 에이전트와 직접 대화(POST /care/agent/chat). 실제 LLM 은 부르지 않고 가짜 LLM 을 끼운다."""

import json

from app.shared.config import settings
from app.shared.llm import agent, agent_chat


def test_agent_chat_reads_meal_log_and_only_has_care_tools(client, family, monkeypatch):
    a, _, _ = family
    client.put(
        "/care/meal-log", json={"date": "2026-10-20", "meal": "lunch", "menu": "비빔밥"}, headers=a
    )
    seen = []

    def fake(body):
        seen.append(body)
        last = body["messages"][-1]
        if isinstance(last["content"], str):
            call = {"type": "tool_use", "id": "t", "name": "list_meal_log"}
            return {"content": [{**call, "input": {"days": 1, "end": "2026-10-20"}}]}
        data = json.dumps(json.loads(last["content"][0]["content"]), ensure_ascii=False)
        return {"content": [{"type": "text", "text": "비빔밥" if "비빔밥" in data else "없음"}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(agent, "_post", fake)
    agent_chat.limiter.reset()
    r = client.post("/care/agent/chat", json={"message": "20일 점심은?"}, headers=a).json()
    assert r["source"] == "ai" and r["reply"] == "비빔밥" and r["tool_calls"] == ["list_meal_log"]
    assert "get_month_summary" not in [t["name"] for t in seen[0]["tools"]]


def test_agent_chat_without_api_key_falls_back(client, family):
    a, _, _ = family
    r = client.post("/care/agent/chat", json={"message": "오늘은?"}, headers=a).json()
    assert r["source"] == "fallback" and r["tool_calls"] == []
