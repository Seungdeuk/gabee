"""LLM 래퍼의 선택 인자 model: 주면 그 모델로, 안 주면 설정값으로 부른다."""

import pytest

from app.shared.config import settings
from app.shared.llm import client as llm


class _Res:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture
def sent(monkeypatch):
    calls: list[dict] = []

    def fake_post(url, json, headers, timeout):
        calls.append(json)
        return _Res({"content": [{"type": "text", "text": "{}"}], "usage": {}})

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    return calls


def test_complete_uses_given_model(sent):
    llm.complete("안녕", model="claude-sonnet-5-5")
    assert sent[0]["model"] == "claude-sonnet-5-5"


def test_complete_defaults_to_setting(sent):
    llm.complete("안녕")
    assert sent[0]["model"] == settings.llm_model


def test_complete_json_uses_given_model(sent):
    result = llm.complete_json("안녕", schema={"type": "object"}, model="claude-sonnet-5-5")
    assert sent[0]["model"] == "claude-sonnet-5-5"
    assert result.model == "claude-sonnet-5-5"


def test_complete_json_defaults_to_setting(sent):
    llm.complete_json("안녕", schema={"type": "object"})
    assert sent[0]["model"] == settings.llm_model
