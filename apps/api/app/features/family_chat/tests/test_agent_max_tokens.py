"""소통 Agent(가족 채팅 탭 에이전트)의 출력 토큰 상한(T35 chat-03): 소통 Agent 호출만 2048, 다른 호출은 그대로. 실제 LLM 은 부르지 않는다.

배경: 기본 상한(1024)에서 모델의 thinking 이 토큰을 다 써 글이 0자로 끝나 `can_answer=false` 가 되거나(빈 응답) 답이 중간에 끊겼다.
"""

import json

import pytest

from app.features.ai_assistant.knowledge import rag_chat
from app.features.family_chat import agent as family_agent
from app.shared.config import settings
from app.shared.llm import agent as llm_agent
from app.shared.llm.agent import Tool, ask_agent
from app.shared.llm.tool_graph import TRUNCATED_NOTE
from tests.ai_consent import enable_ai

SUB_MARK = "가족 채팅 담당"  # 소통 Agent 시스템 프롬프트의 문구


def _text(text, stop="end_turn"):
    return {"content": [{"type": "text", "text": text}], "stop_reason": stop}


def _tool_use(name, args, id_="t1"):
    return {
        "content": [{"type": "tool_use", "id": id_, "name": name, "input": args}],
        "stop_reason": "tool_use",
    }


def _echo_tool():
    return Tool("echo", "에코", {"type": "object", "properties": {}}, lambda args: {"ok": True})


def test_the_family_chat_agent_constant_is_2048_and_the_default_is_unchanged():
    assert family_agent.AGENT_MAX_TOKENS == 2048
    import inspect

    assert inspect.signature(llm_agent.run_agent).parameters["max_tokens"].default == 1024
    assert inspect.signature(llm_agent.ask_agent).parameters["max_tokens"].default is None


def test_ask_agent_passes_a_given_max_tokens_and_keeps_the_default_otherwise():
    bodies = []

    def post(body):
        bodies.append(body)
        return _text("끝")

    ask_agent("시스템", "질문", [_echo_tool()], post=post)
    ask_agent("시스템", "질문", [_echo_tool()], post=post, max_tokens=2048)
    assert [b["max_tokens"] for b in bodies] == [1024, 2048]  # 정산·돌봄처럼 안 주면 기존 1024


def test_the_family_chat_agent_requests_2048_and_the_other_roles_keep_their_limits(
    client, family, monkeypatch
):
    a, _, group = family
    enable_ai(group["id"])
    bodies = []

    def fake_post(body):
        bodies.append(body)
        if SUB_MARK in body["system"]:
            return (
                _text("확인했어요.") if len(body["messages"]) > 1 else _tool_use("list_todos", {})
            )
        if len(body["messages"]) == 1:
            return _tool_use("ask_family_chat", {"question": "할 일을 알려 줘"})
        return _text(json.loads(body["messages"][-1]["content"][0]["content"])["answer"])

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    r = client.post("/ai-assistant/chat", json={"message": "할 일 알려 줘"}, headers=a)
    assert r.status_code == 200, r.text
    sub = [b["max_tokens"] for b in bodies if SUB_MARK in b["system"]]
    main = [b["max_tokens"] for b in bodies if SUB_MARK not in b["system"]]
    assert sub and set(sub) == {2048}
    assert main and set(main) == {rag_chat.CHAT_MAX_TOKENS}  # 메인은 그대로


def test_an_empty_reply_at_the_new_limit_is_still_a_clean_cannot_answer():
    """thinking 만 나오고 글이 0자인 `max_tokens` 응답: 앱은 예외가 아니라 can_answer=false 로 돌려준다(2048 에서도 같다)."""
    seen = []

    def post(body):
        seen.append(body["max_tokens"])
        return {
            "content": [{"type": "thinking", "thinking": "..."}],
            "stop_reason": "max_tokens",
        }

    reply = ask_agent("시스템", "질문", [_echo_tool()], post=post, max_tokens=2048)
    assert seen == [2048]
    assert reply.can_answer is False
    assert reply.answer == "담당 에이전트가 답하지 못했어요: AI 응답이 비어 있어요"


def test_a_cut_off_reply_at_the_new_limit_keeps_its_text_and_gets_the_truncation_note():
    def post(body):
        return {
            "content": [
                {"type": "thinking", "thinking": "..."},
                {"type": "text", "text": "치과 11월 11일"},
            ],
            "stop_reason": "max_tokens",
        }

    reply = ask_agent("시스템", "질문", [_echo_tool()], post=post, max_tokens=2048)
    assert reply.can_answer is True
    assert reply.answer.startswith("치과 11월 11일") and reply.answer.endswith(TRUNCATED_NOTE)


def test_a_normal_reply_at_the_new_limit_has_no_truncation_note():
    reply = ask_agent(
        "시스템", "질문", [_echo_tool()], post=lambda b: _text("완결된 답"), max_tokens=2048
    )
    assert reply.can_answer is True and reply.answer == "완결된 답"


@pytest.mark.parametrize("limit", [1024, 2048])
def test_the_limit_reaches_the_request_body_through_the_tool_loop(limit):
    """도구를 부른 뒤의 두 번째 호출 본문에도 같은 상한이 실린다(마지막 단계 포함)."""
    seen = []

    def post(body):
        seen.append(body["max_tokens"])
        return _tool_use("echo", {}) if len(body["messages"]) == 1 else _text("끝")

    reply = ask_agent("시스템", "질문", [_echo_tool()], post=post, max_tokens=limit)
    assert reply.can_answer is True and seen == [limit, limit]
