"""대화 분석 호출의 출력 상한 4096(T35 chat-03). 상한만 바뀌고 `complete_json` 의 응답 처리·검증, 타임아웃, 다른 Agent 의 상한은 그대로인지 본다.

배경: 분석은 thinking 과 6개 항목 JSON 이 같은 출력 예산을 써서 3000 에 닿으면 잘린 JSON 을 쓸 수 없어 503 이 났다. 실제 Anthropic 은 부르지 않는다.
"""

import inspect
from pathlib import Path

import httpx
import pytest

from app.features.ai_assistant.knowledge import rag_chat
from app.features.family_chat import agent as family_agent
from app.features.family_chat import ai_service
from app.shared.config import Settings, settings
from app.shared.llm import agent as llm_agent
from app.shared.llm import client as llm
from tests.ai_consent import enable_ai

AI = "/family-chat/ai"


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _payload(text="{}", stop="end_turn", out=10):
    return {
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop,
        "usage": {"input_tokens": 7, "output_tokens": out},
        "model": "m-x",
    }


@pytest.fixture
def sent(monkeypatch):
    """`httpx.post` 를 가짜로 바꿔 보낸 본문·타임아웃을 모은다. 응답은 `sent.reply` 로 정한다."""

    class Sent(list):
        reply = _payload()

    s = Sent()

    def post(url, json=None, headers=None, timeout=None):
        s.append({"body": json, "timeout": timeout})
        return _Resp(s.reply)

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_request_cooldown_seconds", 0)
    return s


def test_the_analysis_cap_is_4096_and_every_other_limit_is_unchanged():
    assert ai_service.ANALYSIS_MAX_TOKENS == 4096
    assert Settings().anthropic_max_tokens == 2048  # 일반 호출 기본 상한
    assert family_agent.AGENT_MAX_TOKENS == 2048  # 소통 Agent
    assert rag_chat.CHAT_MAX_TOKENS == 2048  # 메인
    assert (
        inspect.signature(llm_agent.run_agent).parameters["max_tokens"].default == 1024
    )  # 정산 등
    assert inspect.signature(llm.complete_json).parameters["timeout"].default == 40.0  # 타임아웃


def test_the_cap_constant_is_used_only_by_the_analysis_call():
    """공용 분석 호출자(UI 분석 엔드포인트·소통 Agent 도구·일정 제안)는 모두 `ai_service.analysis` 하나를 거친다."""
    source = Path(ai_service.__file__).read_text("utf-8")
    assert source.count("ANALYSIS_MAX_TOKENS") == 2  # 정의 한 곳, 분석 호출 한 곳
    assert "max_tokens=ANALYSIS_MAX_TOKENS" in source
    assert "max_tokens=400" in source and "max_tokens=500" in source  # 답장·주제는 그대로


def test_the_analysis_endpoint_sends_4096_with_the_default_timeout(client, family, sent):
    a, b, _ = family
    assert client.put(f"{AI}/settings", json={"enabled": True}, headers=a).status_code == 200
    for i in range(3):
        r = client.post(
            "/family-chat/messages", json={"text": f"메시지 {i}"}, headers=a if i % 2 else b
        )
        assert r.status_code == 201, r.text
    sent.reply = _payload(
        '{"summary": "요약", "important_messages": [], "schedule_candidates": [], '
        '"todo_candidates": [], "replies": [], "topics": []}'
    )
    r = client.post(f"{AI}/analysis", json={}, headers=a)
    assert r.status_code == 200, r.text
    assert len(sent) == 1
    assert sent[0]["body"]["max_tokens"] == 4096
    assert sent[0]["body"]["output_config"]["effort"] == settings.ai_effort  # effort 는 그대로
    assert sent[0]["timeout"] == 40.0  # 타임아웃은 그대로(`complete_json` 기본값)


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (
            _payload('{"summary": "잘림', "max_tokens", 4096),
            "max_tokens",
        ),  # 4096 에서도 잘린 JSON 은 쓰지 않는다
        (_payload('{"a": 1}', "refusal"), "refusal"),
        (_payload("JSON 아님"), "JSON 이 아니에요"),
        (_payload("[1, 2]"), "형식이 올바르지 않아요"),
    ],
)
def test_complete_json_still_rejects_cut_off_refused_and_invalid_replies_at_4096(
    sent, reply, message
):
    sent.reply = reply
    with pytest.raises(llm.LLMUnavailable) as e:
        llm.complete_json("p", {"type": "object"}, max_tokens=ai_service.ANALYSIS_MAX_TOKENS)
    assert message in str(e.value)
    assert sent[0]["body"]["max_tokens"] == 4096 and len(sent) == 1  # 재시도 없이 한 번만 부른다


def test_a_complete_reply_at_4096_is_parsed_as_before(sent):
    sent.reply = _payload('{"summary": "x"}', "end_turn", 3500)
    res = llm.complete_json("p", {"type": "object"}, max_tokens=ai_service.ANALYSIS_MAX_TOKENS)
    assert res.data == {"summary": "x"} and res.output_tokens == 3500


def test_a_cut_off_analysis_still_ends_as_a_503_llm_failed_and_counts_as_a_call(
    client, family, sent
):
    """상한을 올려도 잘린 응답의 처리(503 llm_failed)와 사용 기록은 그대로다."""
    a, b, group = family
    enable_ai(group["id"])
    for i in range(3):
        client.post("/family-chat/messages", json={"text": f"메시지 {i}"}, headers=a)
    sent.reply = _payload('{"summary": "잘림', "max_tokens", 4096)
    r = client.post(f"{AI}/analysis", json={}, headers=a)
    assert r.status_code == 503 and r.json()["code"] == "llm_failed"
    assert len(sent) == 1 and sent[0]["body"]["max_tokens"] == 4096
