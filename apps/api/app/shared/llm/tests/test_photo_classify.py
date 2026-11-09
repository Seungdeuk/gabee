"""Claude 로 사진이 문서 사진인지 가른다(`doc_ai.classify_photo`). 실제 호출 없이 transport 를 가짜로 바꿔 돈다."""

import base64

import pytest

from app.shared.config import settings
from app.shared.llm import doc_ai, transport


def _reply(kind="document", confidence=0.93, reason="가정통신문을 정면으로 찍음", stop="tool_use"):
    return {
        "stop_reason": stop,
        "content": [
            {
                "type": "tool_use",
                "name": "classify",
                "input": {"kind": kind, "confidence": confidence, "reason": reason},
            }
        ],
        "usage": {"input_tokens": 1700, "output_tokens": 120},
    }


class _Calls(list):
    fake = None


@pytest.fixture
def sent(monkeypatch):
    calls = _Calls()

    def fake(body, *, timeout=60.0, retry=False):
        calls.append(body)
        return fake.reply

    fake.reply = _reply()
    monkeypatch.setattr(transport, "post_messages", fake)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "photo_judge_model", "")
    sent_calls = calls
    sent_calls.fake = fake
    return sent_calls


def test_a_document_answer_is_returned_with_confidence_and_tokens(sent):
    out = doc_ai.classify_photo(b"jpeg-bytes")
    assert (out.kind, out.confidence) == ("document", 0.93)
    assert (out.input_tokens, out.output_tokens) == (1700, 120)
    assert out.reason == "가정통신문을 정면으로 찍음"


def test_the_photo_is_sent_as_one_image_with_the_judge_prompt_and_the_cheap_model(sent):
    doc_ai.classify_photo(b"jpeg-bytes")
    body = sent[0]
    assert body["model"] == settings.llm_model  # 비워 두면 기본(haiku)
    block = body["messages"][0]["content"][0]
    assert block["type"] == "image" and base64.b64decode(block["source"]["data"]) == b"jpeg-bytes"
    assert (
        "photo" in body["system"] and "거리" in body["system"]
    )  # 간판 많은 거리 사진은 문서가 아니라는 안내


def test_the_judge_model_can_be_set_separately(sent, monkeypatch):
    monkeypatch.setattr(settings, "photo_judge_model", "claude-sonnet-5-5")
    doc_ai.classify_photo(b"x")
    assert sent[0]["model"] == "claude-sonnet-5-5"


def test_an_unknown_kind_or_a_missing_answer_is_unavailable_not_a_guess(sent):
    sent.fake.reply = _reply(kind="receipt")
    with pytest.raises(transport.LLMUnavailable):
        doc_ai.classify_photo(b"x")
    sent.fake.reply = {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "문서예요"}],
        "usage": {},
    }
    with pytest.raises(transport.LLMUnavailable):
        doc_ai.classify_photo(b"x")


def test_confidence_is_clamped_to_zero_one(sent):
    sent.fake.reply = _reply(confidence=7)
    assert doc_ai.classify_photo(b"x").confidence == 1.0
    sent.fake.reply = _reply(confidence="높음")
    assert doc_ai.classify_photo(b"x").confidence == 0.0


def test_without_an_api_key_it_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(transport.LLMUnavailable):
        doc_ai.classify_photo(b"x")
