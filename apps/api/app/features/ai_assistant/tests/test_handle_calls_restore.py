"""`rag_chat._handle_calls` 의 이름 되돌리기: 일정 에이전트에게만 원래 이름으로 넘기고, 되돌린 뒤에 고위험 값을 검사한다."""

import json

from app.features.ai_assistant import agents
from app.features.ai_assistant.knowledge import rag_chat

RESTORE = {"[PERSON_1]": "수진", "[SECRET]": "900101-1234567"}


def _restore(text: str) -> str:
    for token, name in RESTORE.items():
        text = text.replace(token, name)
    return text


def _handle(monkeypatch, name: str, question: str):
    """탭 에이전트 호출을 가짜로 바꿔 넘겨받은 인자를 모으고 `_handle_calls` 를 부른다."""
    received: list[dict] = []

    def fake_call(db, group_id, user, agent_name, args, post, audience):
        received.append({"name": agent_name, "args": args})
        return {"answer": "ok", "can_answer": True}, [], [], []

    monkeypatch.setattr(agents, "call", fake_call)
    result = rag_chat.AskResult("", "ai")
    calls = [{"id": "t1", "name": name, "args": {"question": question}}]
    done = rag_chat._handle_calls(
        calls,
        db=None,
        group_id="g",
        user=None,
        audience="me",
        with_agents=True,
        post=lambda body: {},
        result=result,
        seen=set(),
        refs={},
        restore=_restore,
    )
    return received, result, done


def test_ask_schedule_receives_the_restored_name(monkeypatch):
    received, result, done = _handle(monkeypatch, "ask_schedule", "[PERSON_1] 병원 일정 잡아줘")
    assert received == [{"name": "ask_schedule", "args": {"question": "수진 병원 일정 잡아줘"}}]
    # 기록(모델이 부른 그대로)에는 이름표가 남는다
    assert result.tool_calls[0]["input"] == {"question": "[PERSON_1] 병원 일정 잡아줘"}
    assert json.loads(done.outputs[0][1])["answer"] == "ok" and done.outputs[0][2] is False


def test_other_tab_agents_keep_the_name_token(monkeypatch):
    for name in ("ask_billing", "ask_family_chat"):
        received, _, _ = _handle(monkeypatch, name, "[PERSON_1] 지출")
        assert received == [{"name": name, "args": {"question": "[PERSON_1] 지출"}}]


def test_restore_happens_before_the_high_risk_check(monkeypatch):
    """이름표가 풀려 고위험 값이 되면 일정 에이전트까지 가지 않고 모델에 오류로 돌려준다."""
    received, _, done = _handle(monkeypatch, "ask_schedule", "[SECRET] 병원 일정")
    assert received == []
    call_id, text, is_error = done.outputs[0]
    assert is_error is True and "주민번호" in json.loads(text)["error"]


def test_a_token_that_is_not_restored_is_not_refused_for_other_agents(monkeypatch):
    received, _, done = _handle(monkeypatch, "ask_billing", "[SECRET] 지출")
    assert received == [{"name": "ask_billing", "args": {"question": "[SECRET] 지출"}}]
    assert done.outputs[0][2] is False
