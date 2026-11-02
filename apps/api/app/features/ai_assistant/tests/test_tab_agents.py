"""메인 에이전트 → 정산·돌봄 탭 에이전트. 실제 LLM 은 부르지 않고 가짜 LLM 이 도구 호출을 흉내 낸다."""

import json

import pytest
from sqlalchemy import select

from app.features.ai_assistant import agents
from app.features.ai_assistant.knowledge import rag_chat
from app.features.billing import agent as billing_agent
from app.features.care import agent as care_agent
from app.features.family_group.models import User
from app.shared.ai_usage import AiResultCache, AiUsageLog
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.errors import ApiError
from app.shared.llm import agent as llm_agent
from app.shared.llm import agent_guard
from tests.ai_consent import enable_ai


def _tool_use(name, args, id_="t1"):
    return {"content": [{"type": "tool_use", "id": id_, "name": name, "input": args}]}


def _text(text):
    return {"content": [{"type": "text", "text": text}]}


def _last_tool_result(body):
    last = body["messages"][-1]["content"][0]
    assert last["type"] == "tool_result"
    return json.loads(last["content"])


def _user(db, name):
    return db.scalars(select(User).where(User.name == name)).first()


def _spend(client, headers, title, amount, date="2026-10-12"):
    r = client.post(
        "/billing/expenses", json={"title": title, "amount": amount, "date": date}, headers=headers
    )
    assert r.status_code == 201, r.text


def test_main_asks_billing_agent_and_never_gets_db_tools(client, family, monkeypatch):
    a, b, group = family
    enable_ai(group["id"])
    _spend(client, a, "진료비", 30000)
    _spend(client, b, "약", 10000)
    main_tools, sub_results = [], []

    def fake_post(body):
        if "가계(정산) 담당" in body["system"]:  # 정산 에이전트
            if len(body["messages"]) == 1:
                return _tool_use("get_month_summary", {"month": "2026-10"})
            data = _last_tool_result(body)
            sub_results.append(data)
            return _text(f"2026-10 지출은 총 {data['total']:,}원이에요.")
        main_tools.append([t["name"] for t in body["tools"]])  # 메인 에이전트
        if len(body["messages"]) == 1:
            return _tool_use("ask_billing", {"question": "2026년 10월 지출 합계는?"})
        answer = _last_tool_result(body)
        assert answer["can_answer"] is True
        return _text(answer["answer"])

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    r = client.post("/ai-assistant/chat", json={"message": "이번 달 얼마 썼어?"}, headers=a).json()
    assert r["source"] == "ai" and "40,000원" in r["reply"]
    assert sub_results[0]["total"] == 40000
    # 메인은 탭 에이전트와 기록 검색만 쓸 수 있다(가계 DB 를 읽는 도구가 없다). 돌봄 에이전트는 지갑 탭 개편 동안 메인에서 뺐다.
    assert set(main_tools[0]) == {
        "search_knowledge",
        "get_item",
        "list_items",
        "ask_billing",
        "ask_family_chat",
        "ask_schedule",
    }


def test_main_asks_care_agent(client, family, monkeypatch):
    # 돌봄 에이전트는 지금 메인에 연결돼 있지 않다. 다시 연결했을 때 동작하는지 확인하려고 이 테스트 동안만 목록에 넣는다.
    monkeypatch.setitem(agents.AGENTS, "ask_care", (care_agent.DESCRIPTION, care_agent.ask))
    a, _, group = family
    enable_ai(group["id"])
    seen = {}

    def fake_post(body):
        if "돌봄 담당" in body["system"]:
            if len(body["messages"]) == 1:
                return _tool_use("get_today_summary", {})
            seen["sub"] = _last_tool_result(body)
            return _text("오늘 돌봄 기록을 확인했어요.")
        if len(body["messages"]) == 1:
            return _tool_use("ask_care", {"question": "오늘 돌봄 기록은?"})
        return _text(_last_tool_result(body)["answer"])

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    r = client.post("/ai-assistant/chat", json={"message": "오늘 돌봄 어때?"}, headers=a).json()
    assert r["source"] == "ai" and "오늘 돌봄 기록" in r["reply"]
    assert "error" not in seen["sub"]


def test_billing_tools_see_only_own_family(client, family, other_family, monkeypatch):
    a, _, _ = family
    _spend(client, a, "우리 가족 지출", 10000)
    _spend(client, other_family, "남의 가족 지출", 77777)
    with SessionLocal() as db:
        me = _user(db, "지민")
        tools = {t.name: t for t in billing_agent.build_tools(db, me.active_group_id, me)}
        summary = tools["get_month_summary"].run({"month": "2026-10"})
        titles = [e["title"] for e in tools["list_expenses"].run({"month": "2026-10"})["expenses"]]
    assert summary["total"] == 10000
    assert titles == ["우리 가족 지출"]


def test_tab_agent_refuses_non_member(client, family, other_family):
    with SessionLocal() as db:
        member = _user(db, "지민")
        outsider = _user(db, "남")
        for ask in (billing_agent.ask, care_agent.ask):
            with pytest.raises(ApiError) as e:
                ask(db, member.active_group_id, outsider, "질문", None)
            assert (e.value.status, e.value.code) == (403, "not_member")


def test_bad_tool_arguments_are_returned_to_the_agent_as_errors(client, family, monkeypatch):
    a, _, group = family
    enable_ai(group["id"])
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    calls = []

    def fake_post(body):
        calls.append(1)
        if len(calls) == 1:
            return _tool_use("get_month_summary", {"month": "2026-13"})
        result = _last_tool_result(body)
        assert body["messages"][-1]["content"][0]["is_error"] is True
        return _text(f"조회하지 못했어요: {result['error']}")

    with SessionLocal() as db:
        me = _user(db, "지민")
        reply = billing_agent.ask(db, me.active_group_id, me, "13월 지출은?", fake_post)
    assert reply.can_answer and "YYYY-MM" in reply.answer


def test_model_failure_becomes_a_safe_503_and_is_logged(client, family, monkeypatch):
    _, _, group = family
    enable_ai(group["id"])
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    def broken_post(body):
        raise ValueError("boom")

    with SessionLocal() as db:
        me = _user(db, "지민")
        with pytest.raises(ApiError) as e:
            billing_agent.ask(db, me.active_group_id, me, "지출은?", broken_post)
        assert (e.value.status, e.value.code) == (503, "llm_failed")
        row = db.scalars(select(AiUsageLog)).one()
        assert (row.feature, row.status) == ("billing_agent", "error")


def test_chat_without_api_key_still_falls_back(client, family):
    a, _, _ = family
    r = client.post("/ai-assistant/chat", json={"message": "이번 달 지출은?"}, headers=a).json()
    assert r["source"] == "fallback" and r["reply"]


def test_http_error_detail_is_reported(client, family):
    """가드 아래에서는 사용자에게 일반 오류만 보이므로, 원인(상태 코드·API 메시지)은 에이전트 응답에서 확인한다."""
    import httpx

    def refused(body):
        req = httpx.Request("POST", "https://example.test")
        res = httpx.Response(
            400,
            json={
                "error": {"type": "invalid_request_error", "message": "credit balance is too low"}
            },
            request=req,
        )
        raise httpx.HTTPStatusError("bad", request=req, response=res)

    reply = llm_agent.ask_agent("system", "질문", [], post=refused)
    assert not reply.can_answer and "HTTP 400" in reply.answer and "credit balance" in reply.answer


def _ready(monkeypatch, group):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    enable_ai(group["id"])


def test_ai_must_be_enabled_for_the_family(client, family, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(
        settings, "anthropic_api_key", "test-key"
    )  # 키는 있지만 가족이 AI 를 켜지 않았다
    monkeypatch.setattr(llm_agent, "_post", lambda body: _text("호출되면 안 됨"))
    r = client.post("/billing/agent/chat", json={"message": "지출은?"}, headers=a)
    assert (r.status_code, r.json()["code"]) == (403, "ai_not_enabled")
    # 메인 채팅도 같은 관문에서 막힌다. 탭 에이전트 도구(가계·위치)는 가족이 AI 를 켠 뒤에만 주어진다
    monkeypatch.setattr(rag_chat, "_post", lambda body: _text("호출되면 안 됨"))
    r = client.post("/ai-assistant/chat", json={"message": "안녕"}, headers=a)
    assert (r.status_code, r.json()["code"]) == (403, "ai_not_enabled")


def test_usage_is_logged_with_tokens_and_answers_are_not_cached(client, family, monkeypatch):
    a, _, group = family
    _ready(monkeypatch, group)
    reply = {
        "content": [{"type": "text", "text": "네"}],
        "usage": {"input_tokens": 120, "output_tokens": 7},
    }
    monkeypatch.setattr(llm_agent, "_post", lambda body: reply)
    assert (
        client.post("/care/agent/chat", json={"message": "오늘은?"}, headers=a).status_code == 200
    )
    with SessionLocal() as db:
        row = db.scalars(select(AiUsageLog)).one()
        assert (row.feature, row.api_calls, row.status) == ("care_agent", 1, "ok")
        assert (row.input_tokens, row.output_tokens) == (120, 7)
        assert (
            db.scalars(select(AiResultCache)).all() == []
        )  # 가계·위치가 든 답을 캐시에 복사하지 않는다


def test_personal_info_in_the_question_is_masked_before_it_leaves(client, family, monkeypatch):
    a, _, group = family
    _ready(monkeypatch, group)
    sent = []

    def fake(body):
        sent.append(str(body["messages"]))
        return _text("네")

    monkeypatch.setattr(llm_agent, "_post", fake)
    body = {"message": "내 번호는 010-1234-5678 이야. 지출은?"}
    assert client.post("/billing/agent/chat", json=body, headers=a).status_code == 200
    assert "010-1234-5678" not in sent[0] and "지출은" in sent[0]


def test_tab_agent_daily_limit_uses_the_shared_guard(client, family, monkeypatch):
    a, _, group = family
    _ready(monkeypatch, group)
    monkeypatch.setattr(llm_agent, "_post", lambda body: _text("네"))
    monkeypatch.setattr(settings, "ai_tab_agent_max_calls_per_user_per_day", 1)
    agent_guard.register()  # 바뀐 설정을 한도에 반영한다
    try:
        assert (
            client.post("/billing/agent/chat", json={"message": "a"}, headers=a).status_code == 200
        )
        again = client.post(
            "/care/agent/chat", json={"message": "b"}, headers=a
        )  # 정산·돌봄이 한 묶음
        assert (again.status_code, again.json()["code"]) == (429, "ai_daily_limit_user")
    finally:
        monkeypatch.undo()
        agent_guard.register()


def test_false_proposal_claim_is_not_passed_on():
    """에이전트 답이 '확인 버튼을 눌러야 등록돼요'라는데 실제 제안이 없으면 그 말을 전하지 않는다."""
    from app.features.ai_assistant import agents
    from app.shared.llm.agent import AgentReply

    claim = AgentReply("지출 등록을 제안합니다. 아래 확인 버튼을 눌러야 등록됩니다.")
    out = agents._without_false_proposal("ask_billing", claim)
    assert out.can_answer is False and out.answer == agents.NO_PROPOSAL_TEXT
    # 제안이 실제로 있으면 그대로 둔다
    real = AgentReply("지출 등록을 제안합니다. 확인 버튼을 눌러 주세요.", proposals=[object()])
    assert agents._without_false_proposal("ask_billing", real) is real
    # 조회 답이나 다른 에이전트는 건드리지 않는다
    plain = AgentReply("이번 달 지출은 22만원이에요.")
    assert agents._without_false_proposal("ask_billing", plain) is plain
    assert agents._without_false_proposal("ask_schedule", claim) is claim
