"""정산 에이전트와 직접 대화(POST /billing/agent/chat). 실제 LLM 은 부르지 않고 가짜 LLM 을 끼운다."""

import json

from app.shared.config import settings
from app.shared.llm import agent, agent_chat


def _fake_llm(seen):
    def fake(body):
        seen.append({**body, "messages": list(body["messages"])})
        if (
            len(body["messages"])
            and body["messages"][-1]["role"] == "user"
            and isinstance(body["messages"][-1]["content"], str)
        ):
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "get_month_summary",
                        "input": {"month": "2026-10"},
                    }
                ]
            }
        data = json.loads(body["messages"][-1]["content"][0]["content"])
        return {"content": [{"type": "text", "text": f"총 {data['total']:,}원이에요."}]}

    return fake


def test_agent_chat_answers_from_billing_data_and_sends_history(client, family, monkeypatch):
    a, _, _ = family
    client.post(
        "/billing/expenses",
        json={"title": "진료비", "amount": 30000, "date": "2026-10-12"},
        headers=a,
    )
    seen = []
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(agent, "_post", _fake_llm(seen))
    agent_chat.limiter.reset()
    body = {
        "message": "합계는?",
        "history": [
            {"role": "user", "text": "10월 지출 알려줘"},
            {"role": "assistant", "text": "네, 확인할게요"},
        ],
    }
    r = client.post("/billing/agent/chat", json=body, headers=a)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["source"] == "ai" and "30,000원" in out["reply"]
    assert out["tool_calls"] == ["get_month_summary"]
    assert [m["role"] for m in seen[0]["messages"]] == ["user", "assistant", "user"]
    # 이 에이전트는 가계 도구만 가진다
    assert "get_family_locations" not in [t["name"] for t in seen[0]["tools"]]


def test_agent_chat_without_api_key_falls_back(client, family):
    a, _, _ = family
    r = client.post("/billing/agent/chat", json={"message": "지출은?"}, headers=a).json()
    assert r["source"] == "fallback" and r["reply"] and r["tool_calls"] == []


def test_agent_chat_daily_limit_and_membership(client, family, other_family, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(agent, "_post", lambda body: {"content": [{"type": "text", "text": "네"}]})
    monkeypatch.setattr(agent_chat, "DAILY_LIMIT", 1)
    agent_chat.limiter.reset()
    ok = client.post("/billing/agent/chat", json={"message": "안녕"}, headers=a)
    assert ok.status_code == 200
    again = client.post("/billing/agent/chat", json={"message": "또"}, headers=a)
    assert again.status_code == 429 and again.json()["code"] == "daily_limit"
    # 가족 그룹이 없는 사람은 쓸 수 없다
    from tests.helpers import signup

    lone = signup(client, "혼자")
    assert client.post("/billing/agent/chat", json={"message": "x"}, headers=lone).status_code in (
        400,
        403,
        404,
    )
    assert client.post("/billing/agent/chat", json={"message": ""}, headers=a).status_code == 422
