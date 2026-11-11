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
    assert results == []  # 직통 응답: 메인은 일정 에이전트의 답을 다시 다듬지 않는다
    assert "일정을 등록했어요" in reply["reply"] and "엄마 생신" in reply["reply"]
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
    first = _chat(client, a, "내일 2시 일정 잡아줘")
    assert "제목" in first["reply"] and "정보가 더 필요해요" not in first["reply"]
    assert _events(client, a) == []  # 되묻는 동안에는 만들지 않는다

    schedule_llm.data = _register_data(title="치과", date=_tomorrow(), start_time="14:00:00")
    results.clear()
    _main_llm(monkeypatch, "내일 2시 치과 일정 잡아줘", results)
    second = _chat(
        client, a, "치과야"
    )  # 서버가 되묻던 초안을 기억해 두므로 메인이 앞 말을 합치지 않아도 이어진다
    assert "일정을 등록했어요" in second["reply"]
    assert (
        "시작: 14:00" in schedule_llm.calls[-1]
    )  # 이어 받은 초안이 일정 에이전트에 실제로 전달됐다
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
    reply = _chat(client, a, "내일 가족 모임 수진에게도 공유해서 등록해줘")
    assert "공유해서 등록할까요" in reply["reply"] and len(reply["confirm_cards"]) == 1
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
    reply = _chat(client, a, "치과 일정 지워줘")
    assert len(reply["confirm_cards"]) == 1 and reply["confirm_cards"][0]["action"] == "delete"
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


def test_schedule_call_is_counted_under_the_main_chat_not_the_schedule_limit(
    client, family, schedule_llm, monkeypatch
):
    """일정 요청 하나 = 메인 질문의 사용 기록 한 줄(모델 호출 2회: 메인 1 + 일정 1). 일정 한도(schedule_chat)에는 따로 쌓이지 않는다.
    어느 에이전트를 썼는지 보려고 일정 에이전트 이름의 nested 줄(호출 수 0)을 같이 남긴다."""
    from sqlalchemy import select

    from app.shared import ai_guard
    from app.shared.ai_usage import AiUsageLog
    from app.shared.db import SessionLocal

    a, _, group = family
    enable_ai(group["id"])
    user_id = client.get("/family-group/me", headers=a).json()["id"]
    with SessionLocal() as db:
        before = ai_guard.calls_left(db, user_id, group["id"], "schedule_chat")
    schedule_llm.data = _register_data(title="엄마 생신", date=_tomorrow(), start_time="15:00:00")
    _main_llm(monkeypatch, "내일 3시 엄마 생신 일정 잡아줘", [])
    _chat(client, a, "내일 3시 엄마 생신 일정 잡아줘")
    with SessionLocal() as db:
        logs = db.scalars(select(AiUsageLog).where(AiUsageLog.group_id == group["id"])).all()
        assert [(row.feature, row.api_calls, row.status) for row in logs] == [
            ("assistant_chat", 2, "ok"),
            ("schedule_chat", 0, "nested"),
        ]
        # nested 줄은 일정 한도를 쓰지 않는다
        assert ai_guard.calls_left(db, user_id, group["id"], "schedule_chat") == before
    assert len(schedule_llm.calls) == 1


def test_main_chat_ignores_the_schedule_cooldown_and_daily_limit(
    client, family, schedule_llm, monkeypatch
):
    """일정 한도를 0 으로 막아도 메인 채팅 안의 일정 요청은 메인 한도만 따른다(일정 탭 화면이 직접 부르는 입구만 일정 한도를 쓴다)."""
    a, _, group = family
    enable_ai(group["id"])
    from app.shared.ai_usage import AiUsageLog
    from app.shared.db import SessionLocal

    me = client.get("/family-group/me", headers=a).json()["id"]
    with SessionLocal() as db:  # 오늘 일정 한도를 이미 다 쓴 상태
        for _ in range(settings.ai_schedule_chat_max_calls_per_user_per_day):
            db.add(
                AiUsageLog(
                    group_id=group["id"],
                    user_id=me,
                    feature="schedule_chat",
                    api_calls=1,
                    status="ok",
                )
            )
        db.commit()
    schedule_llm.data = _register_data(title="치과", date=_tomorrow(), start_time="14:00:00")
    _main_llm(monkeypatch, "내일 2시 치과 일정 잡아줘", [])
    reply = _chat(client, a, "내일 2시 치과 일정 잡아줘")
    assert "일정을 등록했어요" in reply["reply"]


def test_same_request_twice_registers_only_once(client, family, schedule_llm, monkeypatch):
    a, _, group = family
    enable_ai(group["id"])
    schedule_llm.data = _register_data(title="치과", date=_tomorrow(), start_time="15:00:00")
    _main_llm(monkeypatch, "내일 3시 치과 일정 잡아줘", [])
    first = _chat(client, a, "내일 3시 치과 일정 잡아줘")
    second = _chat(client, a, "내일 3시 치과 일정 잡아줘")
    assert "일정을 등록했어요" in first["reply"]
    assert "이미 같은 일정이 있어요" in second["reply"]
    assert [e["title"] for e in _events(client, a)] == ["치과"]


def test_new_complete_request_does_not_inherit_the_old_draft(
    client, family, schedule_llm, monkeypatch
):
    """되묻다 만 초안(시간 14:00)이 있어도, 제목과 날짜를 모두 말한 새 요청에는 그 시간이 섞이지 않는다."""
    a, _, group = family
    enable_ai(group["id"])
    schedule_llm.data = _register_data(date=_tomorrow(), start_time="14:00:00")
    _main_llm(monkeypatch, "내일 2시 일정 잡아줘", [])
    asked = _chat(client, a, "내일 2시 일정 잡아줘")
    assert "제목" in asked["reply"]
    schedule_llm.data = _register_data(title="엄마 생신", date=_tomorrow())  # 시간 말 안 함
    _main_llm(monkeypatch, "내일 엄마 생신 일정 잡아줘", [])
    _chat(client, a, "내일 엄마 생신 일정 잡아줘")
    saved = _events(client, a)
    assert [e["title"] for e in saved] == ["엄마 생신"]
    assert not saved[0].get("start_time")
