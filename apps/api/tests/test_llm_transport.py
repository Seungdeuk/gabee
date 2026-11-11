"""모델 호출 통합(`app/shared/llm/transport.py`): HTTP 는 한 곳에서만 부르고, 호출한 쪽이 재시도·제한 시간을 고른다."""

from pathlib import Path

import httpx
import pytest

from app.features.ai_assistant.knowledge import rag_chat
from app.shared.config import settings
from app.shared.llm import agent, client, transport

URL = transport.API_URL
APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def _response(status: int, payload: dict | None = None, content: bytes | None = None):
    request = httpx.Request("POST", URL)
    if content is not None:
        return httpx.Response(status, content=content, request=request)
    return httpx.Response(status, json=payload if payload is not None else {}, request=request)


@pytest.fixture
def wire(monkeypatch):
    """httpx.post 를 순서대로 답하는 가짜로 바꾼다. 응답이 예외면 던진다. 기다린 시간도 모은다(실제로 자지 않는다)."""

    class Wire:
        def __init__(self):
            self.queue: list = []
            self.calls: list[dict] = []
            self.sleeps: list[float] = []

    w = Wire()

    def fake_post(url, **kwargs):
        w.calls.append({"url": url, **kwargs})
        item = w.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(transport.httpx, "post", fake_post)
    monkeypatch.setattr(transport.time, "sleep", w.sleeps.append)
    monkeypatch.setattr(settings, "anthropic_api_key", "key-for-test")
    return w


# ---------- 한 번 부르기
def test_success_sends_key_version_and_timeout_and_returns_json(wire):
    wire.queue = [_response(200, {"content": [], "usage": {"input_tokens": 3}})]
    body = {"model": "m", "messages": []}
    out = transport.post_messages(body, timeout=12.5)
    assert out["usage"]["input_tokens"] == 3
    (call,) = wire.calls
    assert call["url"] == URL and call["json"] == body and call["timeout"] == 12.5
    assert call["headers"] == {"x-api-key": "key-for-test", "anthropic-version": "2023-06-01"}
    assert wire.sleeps == []


def test_default_is_a_single_attempt(wire):
    wire.queue = [_response(503), _response(200, {"ok": True})]
    with pytest.raises(httpx.HTTPStatusError):
        transport.post_messages({})
    assert len(wire.calls) == 1 and wire.sleeps == []  # 몰래 다시 부르지 않는다


# ---------- 재시도
@pytest.mark.parametrize("status", sorted(transport.RETRY_STATUS))
def test_retry_once_on_retryable_status(wire, status):
    wire.queue = [_response(status), _response(200, {"ok": True})]
    assert transport.post_messages({}, retry=True) == {"ok": True}
    assert len(wire.calls) == 2 and wire.sleeps == [transport.RETRY_WAIT_SECONDS]


def test_retry_gives_up_after_the_second_failure(wire):
    wire.queue = [_response(529), _response(503), _response(200, {"ok": True})]
    with pytest.raises(httpx.HTTPStatusError):
        transport.post_messages({}, retry=True)
    assert len(wire.calls) == 2  # 두 번까지만


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413])
def test_other_statuses_are_never_retried(wire, status):
    wire.queue = [_response(status), _response(200, {"ok": True})]
    with pytest.raises(httpx.HTTPStatusError):
        transport.post_messages({}, retry=True)
    assert len(wire.calls) == 1


@pytest.mark.parametrize("error", [httpx.ConnectError("boom"), httpx.ReadTimeout("slow")])
def test_connection_failures_retry_once_only_when_asked(wire, error):
    wire.queue = [error, _response(200, {"ok": True})]
    assert transport.post_messages({}, retry=True) == {"ok": True}
    assert len(wire.calls) == 2

    wire.calls.clear()
    wire.queue = [error, _response(200, {"ok": True})]
    with pytest.raises(type(error)):
        transport.post_messages({}, retry=False)
    assert len(wire.calls) == 1


def test_two_connection_failures_in_a_row_raise(wire):
    wire.queue = [httpx.ConnectError("a"), httpx.ConnectError("b")]
    with pytest.raises(httpx.ConnectError):
        transport.post_messages({}, retry=True)
    assert len(wire.calls) == 2


def test_a_body_that_is_not_json_raises_value_error(wire):
    wire.queue = [_response(200, content=b"<html>not json</html>")]
    with pytest.raises(ValueError):
        transport.post_messages({})


# ---------- 토큰 집계
@pytest.mark.parametrize(
    "reply,expected",
    [
        ({"usage": {"input_tokens": 10, "output_tokens": 4}}, (10, 4)),
        ({"usage": {"input_tokens": 7}}, (7, 0)),
        ({"usage": {"input_tokens": None, "output_tokens": None}}, (0, 0)),
        ({"usage": None}, (0, 0)),
        ({}, (0, 0)),
    ],
)
def test_usage_of_never_fails_on_missing_numbers(reply, expected):
    assert transport.usage_of(reply) == expected


# ---------- 세 호출 지점이 모두 transport 를 거치고, 방식만 다르다
@pytest.fixture
def spy(monkeypatch):
    seen: list[dict] = []

    def fake(body, *, timeout=60.0, retry=False):
        seen.append({"body": body, "timeout": timeout, "retry": retry})
        return {"content": []}

    monkeypatch.setattr(transport, "post_messages", fake)
    return seen


def test_tab_agent_retries_with_the_standard_timeout(spy):
    agent._post({"a": 1})
    assert spy == [{"body": {"a": 1}, "timeout": 60.0, "retry": True}]


def test_main_chat_never_retries(spy):
    rag_chat._post({"a": 1})
    assert spy == [{"body": {"a": 1}, "timeout": 60.0, "retry": False}]


def test_client_calls_once_with_the_callers_timeout(spy):
    client._post({"a": 1}, 30.0)
    assert spy == [{"body": {"a": 1}, "timeout": 30.0, "retry": False}]


def test_client_turns_failures_into_llm_unavailable_without_leaking_details(monkeypatch):
    def refused(body, *, timeout=60.0, retry=False):
        raise httpx.ConnectError("secret-host.internal refused key-for-test")

    monkeypatch.setattr(transport, "post_messages", refused)
    with pytest.raises(client.LLMUnavailable) as info:
        client._post({"messages": [{"content": "민감한 질문"}]}, 5.0)
    assert str(info.value) == "AI 호출에 실패했어요 (ConnectError)"
    assert client.LLMUnavailable is transport.LLMUnavailable


# ---------- 앞으로도 한 곳만
def test_only_transport_knows_the_anthropic_endpoint():
    """Anthropic 주소를 아는 코드가 transport.py 하나뿐이어야 한다(랭체인으로 바꿀 때도 이 한 곳만 바꾸면 된다)."""
    owners = [
        path.relative_to(APP_ROOT).as_posix()
        for path in APP_ROOT.rglob("*.py")
        if "tests" not in path.parts and "api.anthropic.com" in path.read_text(encoding="utf-8")
    ]
    assert owners == ["shared/llm/transport.py"]
