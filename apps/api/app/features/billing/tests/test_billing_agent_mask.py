"""정산 에이전트 읽기 도구 결과의 자유 문장 칸(제목·메모)은 외부 모델로 나가기 전에 형식 값(전화 등)을 가린다."""

import json

from app.features.billing.agent import _mask_free_text
from app.shared.config import settings
from app.shared.llm import agent
from tests.ai_consent import enable_ai_for_user

PHONE = "010-1234-5678"


def test_mask_free_text_only_touches_free_text_keys():
    data = {
        "expenses": [{"id": "e1", "title": f"병원비 {PHONE}", "paid_by_name": "지민", "amount": 1}],
        "entries": [{"memo": f"연락 {PHONE}", "date": "2026-10-12"}],
    }
    out = _mask_free_text(data)
    assert PHONE not in json.dumps(out, ensure_ascii=False)
    assert out["expenses"][0]["id"] == "e1" and out["expenses"][0]["paid_by_name"] == "지민"
    assert out["entries"][0]["date"] == "2026-10-12"


def test_list_expenses_result_sent_to_model_has_masked_title(client, family, monkeypatch):
    a, _, _ = family
    client.post(
        "/billing/expenses",
        json={"title": f"치과 {PHONE}", "amount": 30000, "date": "2026-10-12"},
        headers=a,
    )
    seen = []

    def fake(body):
        seen.append(json.dumps(body["messages"], ensure_ascii=False))
        if body["messages"][-1]["role"] == "user" and isinstance(
            body["messages"][-1]["content"], str
        ):
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "list_expenses",
                        "input": {"month": "2026-10"},
                    }
                ]
            }
        return {"content": [{"type": "text", "text": "확인했어요"}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(agent, "_post", fake)
    enable_ai_for_user()
    r = client.post("/billing/agent/chat", json={"message": "10월 지출"}, headers=a)
    assert r.status_code == 200, r.text
    assert r.json()["tool_calls"] == ["list_expenses"]
    sent = "\n".join(seen)
    assert "치과" in sent and PHONE not in sent
