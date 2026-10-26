"""메인 에이전트 → 정산·돌봄 탭 에이전트. 실제 LLM 은 부르지 않고 가짜 LLM 이 도구 호출을 흉내 낸다."""

import json

import pytest
from sqlalchemy import select

from app.features.ai_assistant import service
from app.features.ai_assistant.knowledge import rag_chat
from app.features.billing import agent as billing_agent
from app.features.care import agent as care_agent
from app.features.family_group.models import User
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.errors import ApiError
from app.shared.llm.agent import AgentReply


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
    a, b, _ = family
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
    service._calls.clear()
    r = client.post("/ai-assistant/chat", json={"message": "이번 달 얼마 썼어?"}, headers=a).json()
    assert r["source"] == "ai" and "40,000원" in r["reply"]
    assert sub_results[0]["total"] == 40000
    # 메인은 탭 에이전트와 기록 검색만 쓸 수 있다(가계·돌봄 DB 를 읽는 도구가 없다)
    assert set(main_tools[0]) == {
        "search_knowledge",
        "get_item",
        "list_items",
        "ask_billing",
        "ask_care",
    }


def test_main_asks_care_agent(client, family, monkeypatch):
    a, _, _ = family
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
    service._calls.clear()
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


def test_bad_tool_arguments_are_returned_to_the_agent_as_errors(client, family):
    a, _, _ = family
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


def test_care_locations_hide_coordinates_without_consent(client, family):
    a, b, _ = family
    client.put("/care/location/consent", json={"consent": True}, headers=a)
    with SessionLocal() as db:
        me = _user(db, "지민")
        tools = {t.name: t for t in care_agent.build_tools(db, me.active_group_id, me)}
        members = tools["get_family_locations"].run({})["members"]
    by_name = {m["name"]: m for m in members}
    assert by_name["지민"]["sharing"] is True
    assert by_name["수진"]["sharing"] is False
    assert by_name["수진"]["lat"] is None and by_name["수진"]["lng"] is None


def test_tab_agent_reports_failure_instead_of_raising(client, family):
    def broken_post(body):
        raise ValueError("boom")

    with SessionLocal() as db:
        me = _user(db, "지민")
        reply = billing_agent.ask(db, me.active_group_id, me, "지출은?", broken_post)
    assert isinstance(reply, AgentReply) and reply.can_answer is False


def test_chat_without_api_key_still_falls_back(client, family):
    a, _, _ = family
    r = client.post("/ai-assistant/chat", json={"message": "이번 달 지출은?"}, headers=a).json()
    assert r["source"] == "fallback" and r["reply"]
