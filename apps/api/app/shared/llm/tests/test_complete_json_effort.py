"""complete_json 이 호출마다 추론 정도(effort)를 정할 수 있는지."""

import json

from app.shared.config import settings
from app.shared.llm import client as llm


def _capture(monkeypatch):
    sent = {}

    def fake_post(body, timeout):
        sent["body"] = body
        return {
            "content": [{"type": "text", "text": json.dumps({"ok": True})}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "model": "fake",
        }

    monkeypatch.setattr(llm, "_post", fake_post)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    return sent


def test_complete_json_effort_override(monkeypatch):
    sent = _capture(monkeypatch)
    llm.complete_json("p", {"type": "object"}, effort="low")
    assert sent["body"]["output_config"]["effort"] == "low"


def test_complete_json_effort_defaults_to_setting(monkeypatch):
    sent = _capture(monkeypatch)
    monkeypatch.setattr(settings, "ai_effort", "medium")
    llm.complete_json("p", {"type": "object"})
    assert sent["body"]["output_config"]["effort"] == "medium"
