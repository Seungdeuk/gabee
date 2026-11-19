"""complete_json 이 이미지(JPEG)를 base64 이미지 블록으로 함께 보내는지."""

import base64
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


def test_complete_json_without_images_keeps_string_content(monkeypatch):
    sent = _capture(monkeypatch)
    llm.complete_json("p", {"type": "object"})
    assert sent["body"]["messages"][0]["content"] == "p"


def test_complete_json_sends_image_blocks_before_text(monkeypatch):
    sent = _capture(monkeypatch)
    llm.complete_json("p", {"type": "object"}, images=[b"\xff\xd8jpeg"])
    content = sent["body"]["messages"][0]["content"]
    assert content[0] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.b64encode(b"\xff\xd8jpeg").decode(),
        },
    }
    assert content[-1] == {"type": "text", "text": "p"}
    assert len(content) == 2
