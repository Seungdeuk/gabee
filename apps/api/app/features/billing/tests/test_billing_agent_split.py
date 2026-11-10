"""지출 등록 제안에서 나눌 사람 지정(split_among): 이름 → 가족 구성원 id, 확인해야 반영된다."""

from app.shared.config import settings
from app.shared.llm import agent, proposals
from tests.ai_consent import enable_ai_for_user


def _llm(args):
    calls = []

    def fake(body):
        calls.append(1)
        if len(calls) == 1:
            block = {"type": "tool_use", "id": "t1", "name": "propose_add_expense", "input": args}
            return {"content": [block]}
        return {"content": [{"type": "text", "text": "확인 버튼을 눌러 주세요."}]}

    return fake


def _chat(client, headers, monkeypatch, args):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(agent, "_post", _llm(args))
    enable_ai_for_user()
    proposals.reset()
    r = client.post("/billing/agent/chat", json={"message": "등록해줘"}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


BASE = {"title": "택시", "amount": 12000, "date": "2026-10-12"}


def _expenses(client, headers):
    return client.get("/billing/expenses", params={"month": "2026-10"}, headers=headers).json()


def test_split_among_names_are_resolved_and_applied_after_confirm(client, family, monkeypatch):
    a, _, _ = family
    out = _chat(client, a, monkeypatch, {**BASE, "split_among": ["수진"]})
    (p,) = out["proposals"]
    assert "수진이(가) 나눠요" in p["summary"] and "가족 전원" not in p["summary"]
    assert _expenses(client, a) == []
    assert (
        client.post("/billing/agent/confirm", json={"token": p["token"]}, headers=a).status_code
        == 200
    )
    (e,) = _expenses(client, a)
    assert len(e["split_among"]) == 1 and e["target_tag"] == "custom"


def test_both_members_listed_and_omitted_split(client, family, monkeypatch):
    a, _, _ = family
    both = _chat(client, a, monkeypatch, {**BASE, "split_among": ["지민", "수진", "지민"]})
    assert "지민·수진이(가) 나눠요" in both["proposals"][0]["summary"]
    everyone = _chat(client, a, monkeypatch, BASE)
    assert "가족 전원이 나눠요" in everyone["proposals"][0]["summary"]


def test_unknown_empty_or_malformed_split_makes_no_proposal(client, family, monkeypatch):
    a, _, _ = family
    for bad in (["철수"], [], "수진", [1, 2]):
        out = _chat(client, a, monkeypatch, {**BASE, "split_among": bad})
        assert out["proposals"] == [], bad


def test_a_corrected_proposal_replaces_the_earlier_one(client, family, monkeypatch):
    """같은 지출을 같은 답변에서 고쳐 다시 제안하면 앞선 제안은 확인 버튼으로 남지 않는다."""
    a, _, _ = family
    calls = []

    def fake(body):
        calls.append(1)
        if len(calls) == 1:
            first = {**BASE, "split_among": ["수진"]}
            second = {**BASE, "split_among": ["지민", "수진"]}
            blocks = [
                {"type": "tool_use", "id": "t1", "name": "propose_add_expense", "input": first},
                {"type": "tool_use", "id": "t2", "name": "propose_add_expense", "input": second},
            ]
            return {"content": blocks}
        return {"content": [{"type": "text", "text": "확인 버튼을 눌러 주세요."}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(agent, "_post", fake)
    enable_ai_for_user()
    proposals.reset()
    r = client.post("/billing/agent/chat", json={"message": "등록"}, headers=a).json()
    assert [p["summary"].endswith("지민·수진이(가) 나눠요") for p in r["proposals"]] == [True]


def test_the_asker_name_is_in_the_prompt(client, family):
    from app.features.billing import agent as billing_agent

    assert "질문한 사람은 '지민'" in billing_agent.system_prompt("지민")
    assert "질문한 사람은" not in billing_agent.system_prompt()
