"""탭 에이전트의 도구 반복(`agent.run_agent`, 공통 랭그래프 위에서 돈다): 요청 본문·도구 결과 자르기·오류 변환·횟수 상한·토큰 합."""

import httpx
import pytest

from app.shared.config import settings
from app.shared.errors import ApiError
from app.shared.llm import agent
from app.shared.llm.agent import Tool
from app.shared.llm.transport import LLMUnavailable
from app.shared.privacy.ner import PrivacyUnavailable


def _use(call_id="t1", name="look", args=None):
    return {"type": "tool_use", "id": call_id, "name": name, "input": args or {}}


def _reply(*blocks, usage=(10, 5)):
    return {
        "content": list(blocks),
        "usage": {"input_tokens": usage[0], "output_tokens": usage[1]},
    }


def _text(text, **kw):
    return _reply({"type": "text", "text": text}, **kw)


class Script:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.bodies: list[dict] = []

    def post(self, body):
        self.bodies.append({**body, "messages": list(body["messages"])})
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


def _tool(run, name="look"):
    return Tool(name, "설명", {"type": "object", "properties": {}}, run)


def _run(script, tools, **kw):
    return agent.run_agent(
        "시스템", [{"role": "user", "content": "질문"}], tools, post=script.post, **kw
    )


def test_request_body_and_reply_fields():
    script = Script(_reply(_use(args={"m": 1})), _text(" 답이에요 "))
    seen = []
    reply = _run(script, [_tool(lambda a: seen.append(a) or {"v": 1})], max_tokens=300)
    first, second = script.bodies
    assert first == {
        "model": settings.llm_model,
        "max_tokens": 300,
        "system": "시스템",
        "tools": [
            {"name": "look", "description": "설명", "input_schema": _tool(None).input_schema}
        ],
        "messages": [{"role": "user", "content": "질문"}],
        # 도구 루프는 단계마다 앞 내용을 다시 보내므로 자동 캐시를 켠다(chat_model.py, #371)
        "cache_control": {"type": "ephemeral"},
    }
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    assert second["messages"][1]["content"] == [_use(args={"m": 1})]
    assert second["messages"][2]["content"] == [
        {"type": "tool_result", "tool_use_id": "t1", "content": '{"v": 1}', "is_error": False}
    ]
    assert seen == [{"m": 1}]
    assert reply.answer == "답이에요" and reply.can_answer
    assert reply.tool_calls == [{"name": "look", "input": {"m": 1}}]
    assert (reply.input_tokens, reply.output_tokens) == (20, 10)  # 호출마다의 합
    assert reply.calls == 2 and reply.model == settings.llm_model
    assert reply.proposals == [] and reply.confirmations == []


def test_long_tool_results_are_truncated():
    script = Script(_reply(_use()), _text("끝"))
    _run(script, [_tool(lambda a: {"big": "가" * (agent.MAX_TOOL_RESULT_CHARS + 50)})])
    (result,) = script.bodies[1]["messages"][2]["content"]
    assert len(result["content"]) < agent.MAX_TOOL_RESULT_CHARS + 100
    assert '"truncated": true' in result["content"] and result["is_error"] is False


def test_tool_errors_go_back_to_the_model_with_the_error_flag():
    def boom(args):
        raise ApiError(400, "bad", "고칠 수 있는 오류")

    script = Script(_reply(_use("a"), _use("b", name="nope")), _text("끝"))
    reply = _run(script, [_tool(boom)])
    results = script.bodies[1]["messages"][2]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]  # 한 user 메시지에 모인다
    assert [r["is_error"] for r in results] == [True, True]
    assert "고칠 수 있는 오류" in results[0]["content"]  # ApiError 는 message 를 쓴다
    assert [c["name"] for c in reply.tool_calls] == ["look", "nope"]  # 모르는 도구도 기록


def test_privacy_unavailable_from_a_tool_is_not_swallowed():
    def boom(args):
        raise PrivacyUnavailable()

    script = Script(_reply(_use()), _text("끝"))
    with pytest.raises(PrivacyUnavailable):
        _run(script, [_tool(boom)])
    assert len(script.bodies) == 1


def test_running_out_of_steps_raises_after_running_the_last_tools():
    ran = []
    script = Script(_reply(_use()))  # 계속 도구만 부른다
    with pytest.raises(LLMUnavailable, match="정해진 횟수"):
        _run(script, [_tool(lambda a: ran.append(1) or {})], max_steps=3)
    assert len(script.bodies) == 3 and len(ran) == 3


def test_zero_steps_never_calls_the_model():
    script = Script(_text("x"))
    with pytest.raises(LLMUnavailable, match="정해진 횟수"):
        _run(script, [], max_steps=0)
    assert script.bodies == []


def test_empty_answer_raises():
    with pytest.raises(LLMUnavailable, match="비어 있어요"):
        _run(Script(_text("  ")), [])
    with pytest.raises(LLMUnavailable, match="비어 있어요"):
        _run(Script(_reply()), [])


def test_http_errors_become_llm_unavailable_with_the_same_text():
    response = httpx.Response(429, json={"error": {"type": "rate", "message": "느려요"}})
    status = httpx.HTTPStatusError(
        "x", request=httpx.Request("POST", "http://x"), response=response
    )
    with pytest.raises(LLMUnavailable) as e:
        _run(Script(status), [])
    assert str(e.value) == "AI 호출에 실패했어요 (HTTP 429 rate: 느려요)"
    for error, name in [(httpx.ConnectError("x"), "ConnectError"), (ValueError("j"), "ValueError")]:
        with pytest.raises(LLMUnavailable) as e:
            _run(Script(error), [])
        assert str(e.value) == f"AI 호출에 실패했어요 ({name})"


def test_malformed_tool_use_without_id_becomes_llm_unavailable_before_any_tool_runs():
    ran = []
    bad = {"type": "tool_use", "name": "look", "input": {}}
    with pytest.raises(LLMUnavailable, match="KeyError"):
        _run(Script(_reply(bad)), [_tool(lambda a: ran.append(1) or {})])
    assert ran == []


def test_without_a_key_or_post_it_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(LLMUnavailable, match="ANTHROPIC_API_KEY"):
        agent.run_agent("s", [{"role": "user", "content": "q"}], [])


def test_default_post_retries_and_the_history_turns_are_sent_as_given(monkeypatch):
    """post 를 안 주면 재시도하는 `_post` 를 쓴다. 앞 대화는 user/assistant 글 그대로 요청에 담긴다."""
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    sent = []
    monkeypatch.setattr(
        agent.transport,
        "post_messages",
        lambda body, *, timeout, retry: sent.append((body, timeout, retry)) or _text("안녕"),
    )
    history = [
        {"role": "user", "content": "앞 질문"},
        {"role": "assistant", "content": "앞 답"},
        {"role": "user", "content": "지금 질문"},
    ]
    assert agent.run_agent("s", history, []).answer == "안녕"
    ((body, timeout, retry),) = sent
    assert body["messages"] == history and timeout == 60.0 and retry is True
