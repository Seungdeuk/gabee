"""모델 호출(`agent._post`)의 일시 오류 재시도: 연결·시간 초과·429/5xx/529 는 한 번 더 시도하고, 그 밖의 오류는 바로 실패한다."""

import httpx
import pytest

from app.shared.config import settings
from app.shared.llm import agent
from app.shared.llm.client import LLMUnavailable


def _resp(status: int, body: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=body or {}, request=httpx.Request("POST", agent.API_URL))


@pytest.fixture
def calls(monkeypatch):
    """httpx.post 를 가짜로 바꾸고 time.sleep 을 없앤다. 반환값: 부른 횟수가 담긴 리스트."""
    monkeypatch.setattr(agent.time, "sleep", lambda _s: None)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    return []


def _script(monkeypatch, calls, results):
    items = iter(results)

    def fake_post(*_a, **_k):
        calls.append(1)
        item = next(items)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(agent.httpx, "post", fake_post)


OK = {"content": [{"type": "text", "text": "안녕"}]}


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 529])
def test_retries_once_on_transient_status(monkeypatch, calls, status):
    _script(monkeypatch, calls, [_resp(status), _resp(200, OK)])
    assert agent._post({}) == OK
    assert len(calls) == 2


@pytest.mark.parametrize("exc", [httpx.ConnectError("x"), httpx.ReadTimeout("x")])
def test_retries_once_on_connection_error_and_timeout(monkeypatch, calls, exc):
    _script(monkeypatch, calls, [exc, _resp(200, OK)])
    assert agent._post({}) == OK
    assert len(calls) == 2


def test_gives_up_after_second_failure(monkeypatch, calls):
    _script(monkeypatch, calls, [_resp(529), _resp(529)])
    with pytest.raises(httpx.HTTPStatusError):
        agent._post({})
    assert len(calls) == 2
    _script(monkeypatch, calls, [httpx.ConnectError("x"), httpx.ConnectError("y")])
    with pytest.raises(httpx.ConnectError):
        agent._post({})


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_does_not_retry_client_errors(monkeypatch, calls, status):
    _script(monkeypatch, calls, [_resp(status), _resp(200, OK)])
    with pytest.raises(httpx.HTTPStatusError):
        agent._post({})
    assert len(calls) == 1


def test_run_agent_turns_exhausted_retry_into_llm_unavailable(monkeypatch, calls):
    _script(monkeypatch, calls, [_resp(503), _resp(503)])
    with pytest.raises(LLMUnavailable, match="HTTP 503"):
        agent.run_agent("sys", [{"role": "user", "content": "hi"}], [])
