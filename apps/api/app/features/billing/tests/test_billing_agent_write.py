"""정산 에이전트의 쓰기: 제안만 하고, 사용자가 확인(agent/confirm)해야 실제로 등록된다."""

from datetime import timedelta

import jwt

from app.features.ai_assistant import service as chat_service
from app.features.ai_assistant.knowledge import rag_chat
from app.shared import tokens
from app.shared.config import settings
from app.shared.llm import agent, agent_chat, proposals
from tests.helpers import signup

EXPENSE = {"title": "치과", "amount": 50000, "date": "2026-10-12"}


def _tool_use(name, args, id_="t1"):
    return {"content": [{"type": "tool_use", "id": id_, "name": name, "input": args}]}


def _proposing_llm(args=None, times=1):
    """propose_add_expense 를 times 번 부르고 마지막에 안내 문장으로 끝내는 가짜 LLM."""
    calls = []

    def fake(body):
        if "가계(정산) 담당" not in body["system"]:
            return {"content": [{"type": "text", "text": "메인"}]}
        calls.append(1)
        if len(calls) <= times:
            return _tool_use("propose_add_expense", args or EXPENSE, f"t{len(calls)}")
        return {"content": [{"type": "text", "text": "확인 버튼을 눌러 주세요."}]}

    return fake


def _setup(monkeypatch, fake):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(agent, "_post", fake)
    agent_chat.limiter.reset()
    proposals.reset()


def _expenses(client, headers):
    return client.get("/billing/expenses", params={"month": "2026-10"}, headers=headers).json()


def test_proposal_does_not_write_until_confirmed(client, family, monkeypatch):
    a, _, _ = family
    _setup(monkeypatch, _proposing_llm())
    r = client.post(
        "/billing/agent/chat", json={"message": "치과 5만원 등록해줘"}, headers=a
    ).json()
    assert r["source"] == "ai" and r["tool_calls"] == ["propose_add_expense"]
    (p,) = r["proposals"]
    assert p["tab"] == "billing" and "치과 50,000원" in p["summary"]
    assert _expenses(client, a) == []  # 제안만으로는 등록되지 않는다
    ok = client.post("/billing/agent/confirm", json={"token": p["token"]}, headers=a)
    assert ok.status_code == 200 and ok.json() == {"ok": True, "summary": p["summary"]}
    (e,) = _expenses(client, a)
    assert (e["title"], e["amount"]) == ("치과", 50000)


def test_confirm_rejects_other_user_family_tab_reuse_and_forgery(client, family, monkeypatch):
    a, b, _ = family
    outsider = signup(client, "남")
    client.post("/family-group/groups", json={"name": "다른 가족"}, headers=outsider)
    _setup(monkeypatch, _proposing_llm())
    chat = client.post("/billing/agent/chat", json={"message": "등록"}, headers=a).json()
    token = chat["proposals"][0]["token"]

    def confirm(headers, tok=token, tab="billing"):
        return client.post(f"/{tab}/agent/confirm", json={"token": tok}, headers=headers)

    assert confirm(b).json()["code"] == "proposal_invalid"  # 같은 가족의 다른 사람
    assert confirm(outsider).json()["code"] == "proposal_invalid"  # 다른 가족
    assert confirm(a, tab="care").json()["code"] == "proposal_invalid"  # 다른 탭
    assert confirm(a, tok=token[:-3] + "abc").json()["code"] == "proposal_invalid"  # 위조
    assert confirm(a, tok="not-a-token-at-all").json()["code"] == "proposal_invalid"
    assert _expenses(client, a) == []
    assert confirm(a).status_code == 200
    assert confirm(a).status_code == 409  # 한 번만
    assert len(_expenses(client, a)) == 1


def test_expired_and_non_proposal_tokens_are_rejected(client, family, monkeypatch):
    a, _, _ = family
    _setup(monkeypatch, _proposing_llm())
    monkeypatch.setattr(proposals, "TTL", timedelta(seconds=-5))
    chat = client.post("/billing/agent/chat", json={"message": "등록"}, headers=a).json()
    token = chat["proposals"][0]["token"]
    r = client.post("/billing/agent/confirm", json={"token": token}, headers=a)
    assert r.json()["code"] == "proposal_expired"
    # 같은 비밀키로 서명했지만 다른 용도(aud)의 토큰은 통하지 않는다
    claims = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": "x",
        "jti": "j",
        "iat": 1,
        "exp": 9999999999,
    }
    forged = jwt.encode(claims, tokens._secret(), algorithm="HS256")
    r = client.post("/billing/agent/confirm", json={"token": forged}, headers=a)
    assert r.json()["code"] == "proposal_invalid"
    assert _expenses(client, a) == []


def test_invalid_or_excess_proposals_are_not_created(client, family, monkeypatch):
    a, _, _ = family
    _setup(monkeypatch, _proposing_llm({"title": "치과", "amount": -5}))
    r = client.post("/billing/agent/chat", json={"message": "등록"}, headers=a).json()
    assert r["proposals"] == []  # 검증 실패는 제안으로 이어지지 않는다
    # 한 번의 모델 응답에서 다섯 건을 한꺼번에 제안해도 상한까지만 만들어진다
    calls = []

    def many(body):
        calls.append(1)
        if len(calls) == 1:
            blocks = [
                {"type": "tool_use", "id": f"t{i}", "name": "propose_add_expense", "input": EXPENSE}
                for i in range(5)
            ]
            return {"content": blocks}
        return {"content": [{"type": "text", "text": "확인해 주세요."}]}

    _setup(monkeypatch, many)
    r = client.post("/billing/agent/chat", json={"message": "등록"}, headers=a).json()
    assert len(r["proposals"]) == proposals.MAX_PER_ANSWER


def test_main_chat_passes_proposal_to_user(client, family, monkeypatch):
    a, _, _ = family
    sub = _proposing_llm()

    def fake(body):
        if "가계(정산) 담당" in body["system"]:
            return sub(body)
        last = body["messages"][-1]
        if isinstance(last["content"], str):
            return _tool_use("ask_billing", {"question": "치과 50000원 지출 등록해줘"})
        return {"content": [{"type": "text", "text": "확인 버튼을 눌러 주세요."}]}

    _setup(monkeypatch, fake)
    monkeypatch.setattr(rag_chat, "_post", fake)
    chat_service._calls.clear()
    r = client.post("/ai-assistant/chat", json={"message": "치과 5만원 등록해줘"}, headers=a).json()
    assert r["source"] == "ai" and len(r["proposals"]) == 1
    assert r["proposals"][0]["tab"] == "billing" and _expenses(client, a) == []
