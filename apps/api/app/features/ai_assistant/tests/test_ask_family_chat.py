"""메인 에이전트 → 가족 채팅 탭 에이전트(ask_family_chat). 실제 LLM 은 부르지 않고 가짜가 도구 호출을 흉내 낸다."""

import json
import re

import pytest

from app.features.ai_assistant import agents
from app.features.ai_assistant.knowledge import rag_chat
from app.shared.config import settings
from app.shared.llm import client as llm
from tests.ai_consent import enable_ai

MSG = "/family-chat/messages"
TODOS = "/family-chat/todos"
DIRECT_ROOM = "/family-chat/rooms/direct"
SUB_MARK = "가족 채팅 담당"  # 탭 에이전트 시스템 프롬프트에 있는 문구


def _tool_use(name, args, id_="t1"):
    return {"content": [{"type": "tool_use", "id": id_, "name": name, "input": args}]}


def _text(text):
    return {"content": [{"type": "text", "text": text}]}


def _last_tool_result(body):
    last = body["messages"][-1]["content"][0]
    assert last["type"] == "tool_result"
    return last["content"]


def _say(client, headers, text, room_id=None):
    body = {"text": text} if room_id is None else {"text": text, "room_id": room_id}
    r = client.post(MSG, json=body, headers=headers)
    assert r.status_code == 201, r.text


def _chat(client, headers, message="질문"):
    return client.post("/ai-assistant/chat", json={"message": message}, headers=headers).json()


def _fake(monkeypatch, sub_tool, sub_args, sub_answer=None):
    """메인은 ask_family_chat 을 부르고, 탭 에이전트는 sub_tool 을 한 번 부른 뒤 답한다. 도구 결과 글을 seen 에 모은다."""
    seen = {"sub_result": None, "main_tools": None, "answer": None}

    def fake_post(body):
        if SUB_MARK in body["system"]:
            if len(body["messages"]) == 1:
                return _tool_use(sub_tool, sub_args)
            seen["sub_result"] = _last_tool_result(body)
            answer = sub_answer(seen["sub_result"]) if sub_answer else "확인했어요."
            return _text(answer)
        seen["main_tools"] = [t["name"] for t in body["tools"]]
        if len(body["messages"]) == 1:
            return _tool_use("ask_family_chat", {"question": "채팅에서 병원 얘기 언제 했지?"})
        data = json.loads(_last_tool_result(body))
        seen["answer"] = data
        return _text(data["answer"])

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    return seen


def test_tool_is_listed_for_main_agent(client, family, monkeypatch):
    assert "ask_family_chat" in [spec["name"] for spec in agents.tool_specs()]
    assert agents.is_agent_tool("ask_family_chat")
    a, _, group = family
    enable_ai(group["id"])
    seen = _fake(monkeypatch, "list_todos", {})
    _chat(client, a)
    assert "ask_family_chat" in seen["main_tools"]


def test_ask_without_ai_consent_is_refused_before_any_model_call(client, family, monkeypatch):
    a, _, _ = family  # 가족 AI 동의를 켜지 않았다
    calls = []
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", lambda body: calls.append(body) or _text("x"))
    r = client.post("/ai-assistant/chat", json={"message": "채팅 요약해줘"}, headers=a)
    assert r.status_code == 403 and calls == []


def test_search_returns_family_room_messages_tokenized_and_answer_is_restored(
    client, family, monkeypatch
):
    a, b, group = family
    enable_ai(group["id"])
    _say(client, a, "병원 예약은 금요일 오후로 하자")
    _say(client, b, "응 병원은 내가 갈게. 내 번호는 010-1234-5678")

    def answer(tool_result):
        token = re.search(r"\[PERSON_\d+\]", tool_result).group(0)
        return f"{token}가 병원에 가기로 했어요."

    seen = _fake(monkeypatch, "search_messages", {"query": "병원"}, answer)
    reply = _chat(client, a)
    result = seen["sub_result"]
    assert "010-1234-5678" not in result  # 전화번호는 모델로 가지 않는다
    assert "수진" not in result and "지민" not in result  # 이름은 토큰으로 바뀐다
    assert "병원" in result and '"from_me": true' in result
    # 탭 에이전트의 답을 메인이 그대로 돌려준다(직통 응답): 토큰이 이름으로 복원돼 있다
    assert "수진이 병원에 가기로 했어요" in reply["reply"]
    assert reply["source"] == "ai"


def test_search_never_returns_direct_messages(client, family, monkeypatch):
    a, b, group = family
    enable_ai(group["id"])
    peer = client.get("/family-group/me", headers=b).json()["id"]
    room = client.post(DIRECT_ROOM, json={"user_id": peer}, headers=a).json()["id"]
    _say(client, a, "비밀병원 얘기는 둘이서만", room_id=room)
    _say(client, a, "가족방에서는 병원 얘기 안 해")
    seen = _fake(monkeypatch, "search_messages", {"query": "비밀병원"})
    _chat(client, a)
    assert "비밀병원" not in seen["sub_result"]
    assert json.loads(seen["sub_result"])["messages"] == []


def test_todos_tool_shows_assignee_token_and_no_ids(client, family, monkeypatch):
    a, b, group = family
    enable_ai(group["id"])
    peer = client.get("/family-group/me", headers=b).json()["id"]
    r = client.post(
        TODOS, json={"title": "장보기", "assignee_id": peer, "due_date": "2026-11-01"}, headers=a
    )
    assert r.status_code == 201, r.text
    seen = _fake(monkeypatch, "list_todos", {"status": "open"})
    _chat(client, a)
    todos = json.loads(seen["sub_result"])["todos"]
    assert todos[0]["title"] == "장보기" and todos[0]["due_date"] == "2026-11-01"
    assert todos[0]["assignee"] != "수진" and todos[0]["assignee"].startswith("[PERSON_")
    assert peer not in seen["sub_result"]


@pytest.fixture
def fake_analysis(monkeypatch):
    def complete(prompt, schema, system=None, max_tokens=None, **kw):
        data = {
            "summary": "토요일 저녁 식사를 정했어요.",
            "important_messages": [],
            "schedule_candidates": [],
            "todo_candidates": [],
        }
        return llm.JsonResult(data=data, input_tokens=100, output_tokens=20, model="fake")

    monkeypatch.setattr(llm, "complete_json", complete)
    monkeypatch.setattr(llm, "available", lambda: True)


def test_analysis_runs_inside_main_chat_without_busy_error(
    client, family, monkeypatch, fake_analysis
):
    a, b, group = family
    enable_ai(group["id"])
    for i in range(4):
        _say(client, a if i % 2 == 0 else b, f"토요일 저녁 같이 먹자 {i}")
    seen = _fake(monkeypatch, "analyze_recent_chat", {"limit": 50})
    _chat(client, a)
    data = json.loads(seen["sub_result"])
    assert "error" not in data, data  # 메인이 쥔 동시 실행 칸 안에서 분석이 거절되지 않는다
    assert data["summary"] == "토요일 저녁 식사를 정했어요."
    assert "meta" not in data


def test_analysis_with_too_few_messages_is_reported_as_tool_error(client, family, monkeypatch):
    a, _, group = family
    enable_ai(group["id"])
    seen = _fake(monkeypatch, "analyze_recent_chat", {})
    _chat(client, a)
    assert "error" in json.loads(seen["sub_result"])


def test_particles_after_restored_names_follow_batchim():
    from app.features.family_chat.agent import fix_particles

    names = ["수진", "지아", "지민"]
    assert fix_particles("수진가 병원에 가요", names) == "수진이 병원에 가요"
    assert fix_particles("지아은 학교에 가요", names) == "지아는 학교에 가요"
    assert (
        fix_particles("지민를 만났고 수진와 지아을 봤어요", names)
        == "지민을 만났고 수진과 지아를 봤어요"
    )
    assert fix_particles("지민랑 지아이랑 수진이 갔어요", names) == "지민이랑 지아랑 수진이 갔어요"
    # 이미 맞는 표현과 이름이 아닌 글은 그대로 둔다
    assert (
        fix_particles("수진이 지민은 지아가 가요. 가격은 그대로", names)
        == "수진이 지민은 지아가 가요. 가격은 그대로"
    )


def test_message_times_are_shown_in_service_timezone(monkeypatch):
    from app.features.family_chat.agent import _local_time

    monkeypatch.setattr(settings, "ai_day_utc_offset_hours", 9)
    assert _local_time("2026-10-27T03:55:00") == "2026-10-27 12:55"
    assert _local_time("2026-10-27T23:30:00+00:00") == "2026-10-28 08:30"
