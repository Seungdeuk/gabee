"""메인 에이전트 → 일정 탭 에이전트(ask_schedule). 메인 LLM 은 rag_chat._post, 일정 LLM 은 llm.complete_json 을 가짜로 바꾼다."""

import json
from datetime import timedelta

import pytest

from app.features.ai_assistant import agents
from app.features.ai_assistant.knowledge import rag_chat
from app.features.schedule.agent import register
from app.shared.config import settings
from app.shared.llm import client as llm
from tests.ai_consent import enable_ai


def _tool_use(name, args, id_="t1"):
    return {"content": [{"type": "tool_use", "id": id_, "name": name, "input": args}]}


def _text(text):
    return {"content": [{"type": "text", "text": text}]}


def _last_tool_result(body):
    last = body["messages"][-1]["content"][0]
    assert last["type"] == "tool_result"
    return json.loads(last["content"])


def _tomorrow() -> str:
    return (register.today() + timedelta(days=1)).isoformat()


def _register_data(**fields):
    base = {
        "title": "",
        "date": "",
        "start_time": "",
        "end_time": "",
        "kind": 0,
        "place": "",
        "memo": "",
        "who_ids": [],
        "share_ids": [],
        "date_ambiguous": False,
    }
    base.update(fields)
    return {"intent": "register", "reply": "", "event_ids": [], "register": base}


class FakeScheduleLLM:
    def __init__(self):
        self.calls = []
        self.data = {}

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append(prompt)
        return llm.JsonResult(data=self.data, input_tokens=100, output_tokens=20, model="fake")


@pytest.fixture
def schedule_llm(monkeypatch):
    fake = FakeScheduleLLM()
    monkeypatch.setattr(llm, "complete_json", fake)
    monkeypatch.setattr(llm, "available", lambda: True)
    return fake


def _main_llm(monkeypatch, question, results):
    """메인이 ask_schedule 로 question 을 넘기고, 돌려받은 결과를 results 에 모은 뒤 answer 를 그대로 전한다."""

    def fake_post(body):
        if len(body["messages"]) == 1:
            return _tool_use("ask_schedule", {"question": question})
        data = _last_tool_result(body)
        results.append(data)
        return _text(data["answer"])

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)


def _events(client, headers):
    return client.get("/schedule/events", params={"include_past": True}, headers=headers).json()


def _chat(client, headers, message):
    return client.post("/ai-assistant/chat", json={"message": message}, headers=headers).json()


def test_birthday_sentence_registers_own_event(client, family, schedule_llm, monkeypatch):
    a, _, group = family
    enable_ai(group["id"])
    schedule_llm.data = _register_data(title="엄마 생신", date=_tomorrow(), start_time="15:00:00")
    results = []
    _main_llm(monkeypatch, "내일 3시 엄마 생신이야", results)
    reply = _chat(client, a, "내일 3시 엄마 생신이야")
    assert "error" not in results[0], results[0]
    assert results[0]["can_answer"] is True and "일정을 등록했어요" in results[0]["answer"]
    assert "엄마 생신" in reply["reply"]
    saved = _events(client, a)
    assert [e["title"] for e in saved] == ["엄마 생신"]


def test_missing_title_asks_back_then_full_sentence_registers(
    client, family, schedule_llm, monkeypatch
):
    a, _, group = family
    enable_ai(group["id"])
    schedule_llm.data = _register_data(date=_tomorrow(), start_time="14:00:00")
    results = []
    _main_llm(monkeypatch, "내일 2시 일정 잡아줘", results)
    _chat(client, a, "내일 2시 일정 잡아줘")
    assert results[0]["can_answer"] is True and "제목" in results[0]["answer"]
    assert _events(client, a) == []  # 되묻는 동안에는 만들지 않는다

    schedule_llm.data = _register_data(title="치과", date=_tomorrow(), start_time="14:00:00")
    results.clear()
    _main_llm(monkeypatch, "내일 2시 치과 일정 잡아줘", results)
    _chat(client, a, "치과야")
    assert "일정을 등록했어요" in results[0]["answer"]
    assert [e["title"] for e in _events(client, a)] == ["치과"]


def test_share_register_is_not_executed_in_chat(client, family, schedule_llm, monkeypatch):
    a, b, group = family
    enable_ai(group["id"])
    other = client.get("/family-group/me", headers=b).json()["id"]
    schedule_llm.data = _register_data(
        title="가족 모임", date=_tomorrow(), kind=1, share_ids=[other]
    )
    results = []
    _main_llm(monkeypatch, "내일 가족 모임 수진에게도 공유해서 등록해줘", results)
    _chat(client, a, "내일 가족 모임 수진에게도 공유해서 등록해줘")
    assert "아직 실행되지 않았어요" in results[0]["answer"]
    assert _events(client, a) == [] and _events(client, b) == []


def test_delete_is_not_executed_in_chat(client, family, schedule_llm, monkeypatch):
    a, _, group = family
    enable_ai(group["id"])
    created = client.post(
        "/schedule/events",
        json={"title": "치과", "start_date": _tomorrow(), "start_time": "14:00:00"},
        headers=a,
    ).json()
    schedule_llm.data = {
        "intent": "delete",
        "reply": "",
        "event_ids": [],
        "target_id": created["id"],
        "changes": {
            "title": "",
            "date": "",
            "start_time": "",
            "end_time": "",
            "kind": 0,
            "place": "",
            "memo": "",
            "clear": [],
        },
    }
    results = []
    _main_llm(monkeypatch, "치과 일정 지워줘", results)
    _chat(client, a, "치과 일정 지워줘")
    assert "아직 실행되지 않았어요" in results[0]["answer"]
    assert [e["title"] for e in _events(client, a)] == ["치과"]


def test_non_schedule_question_cannot_be_answered(client, family, schedule_llm, monkeypatch):
    a, _, group = family
    enable_ai(group["id"])
    schedule_llm.data = {"intent": "not_schedule", "reply": "", "event_ids": []}
    results = []
    _main_llm(monkeypatch, "파이썬 정렬 코드 짜줘", results)
    _chat(client, a, "파이썬 정렬 코드 짜줘")
    assert results[0]["can_answer"] is False


def test_schedule_tool_is_listed_for_main_agent():
    names = [spec["name"] for spec in agents.tool_specs()]
    assert "ask_schedule" in names and agents.is_agent_tool("ask_schedule")


def test_chat_without_ai_consent_is_refused_before_any_model_call(client, family, monkeypatch):
    a, _, _ = family  # 가족 AI 동의를 켜지 않았다
    calls = []

    def fake_post(body):
        calls.append(body)
        return _text("안녕하세요")

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    r = client.post("/ai-assistant/chat", json={"message": "내일 3시 엄마 생신이야"}, headers=a)
    assert r.status_code == 403 and calls == []  # 모델도, 일정 에이전트도 불리지 않는다
