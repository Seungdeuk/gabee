"""챙길 일 뽑기 체인(doc_ai.REMINDER_CHAIN): 가짜 transport.post_messages 로 요청 본문과 응답 읽기를 시험한다. 외부 호출 없음, 값은 모두 가상이다."""

import threading

import httpx
import pytest

from app.shared.config import settings
from app.shared.llm import doc_ai, transport
from app.shared.llm.transport import LLMUnavailable


class FakeClaude:
    def __init__(self, reminders=None, content=None):
        self.calls: list[dict] = []
        self.kwargs: list[dict] = []
        self.threads: list[int] = []
        self.content = content
        self.reminders = reminders if reminders is not None else []
        self.fail: Exception | None = None

    def __call__(self, body, *, timeout, retry):
        self.calls.append(body)
        self.kwargs.append({"timeout": timeout, "retry": retry})
        self.threads.append(threading.get_ident())
        if self.fail:
            raise self.fail
        if self.content is not None:
            return {"content": self.content}
        return {
            "content": [
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "report_reminders",
                    "input": {"reminders": self.reminders},
                }
            ]
        }


@pytest.fixture
def claude(monkeypatch):
    fake = FakeClaude()
    monkeypatch.setattr(transport, "post_messages", fake)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "ingest_mask_model", "")
    monkeypatch.setattr(settings, "llm_model", "claude-haiku-4-5")
    return fake


def _plan():
    return doc_ai.plan_reminders("가정통신문", "체험학습 11월 12일", ["2026-11-12"], "2026-11-06")


def test_chain_sends_the_same_body_as_before(claude):
    _plan()
    body = claude.calls[0]
    assert body["model"] == "claude-haiku-4-5"
    assert body["max_tokens"] == 1024
    assert body["system"] == doc_ai.REMIND_SYSTEM
    assert body["tools"] == [doc_ai.REMIND_TOOL]
    assert body["tool_choice"] == {"type": "tool", "name": "report_reminders"}
    assert body["messages"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "오늘 날짜: 2026-11-06\n문서 제목: 가정통신문\n"
                    "문서에서 찾은 날짜: 2026-11-12\n\n<문서>\n체험학습 11월 12일\n</문서>",
                }
            ],
        }
    ]
    assert claude.kwargs[0] == {"timeout": 60.0, "retry": True}
    assert set(body) == {"model", "max_tokens", "system", "messages", "tools", "tool_choice"}


def test_chain_uses_mask_model_when_set_and_sonnet_tool_choice(claude, monkeypatch):
    monkeypatch.setattr(settings, "ingest_mask_model", "claude-sonnet-5-5")
    _plan()
    body = claude.calls[0]
    assert body["model"] == "claude-sonnet-5-5"
    assert body["tool_choice"] == {"type": "auto"}
    assert body["system"] == doc_ai.REMIND_SYSTEM + "\n\n반드시 report_reminders 도구로만 답하세요."


def test_chain_runs_on_the_callers_thread(claude):
    _plan()
    assert claude.threads == [threading.get_ident()]


def test_chain_parses_reminders_with_place_prep_memo(claude):
    claude.reminders = [
        {
            "label": " 현장체험학습 동의서 제출 ",
            "date": "2026-11-12",
            "time": "09:00",
            "urgent": True,
            "lead_days": 2,
            "place": "국립중앙박물관",
            "prep": "도시락, 물",
            "memo": "운동화 착용",
        },
        {"label": "알림", "date": "2026-11-13", "urgent": False},
    ]
    a, b = _plan()
    assert (a.label, a.date, a.time, a.urgent, a.lead_days) == (
        "현장체험학습 동의서 제출",
        "2026-11-12",
        "09:00",
        True,
        2,
    )
    assert (a.place, a.prep, a.memo) == ("국립중앙박물관", "도시락, 물", "운동화 착용")
    assert (b.time, b.place, b.prep, b.memo, b.lead_days, b.urgent) == ("", "", "", "", 0, False)


def test_chain_handles_malformed_items_like_before(claude):
    claude.reminders = [
        "문자열",
        None,
        7,
        {"label": "a", "date": "2026-11-12", "urgent": True, "lead_days": "2"},
        {"label": "b", "date": "2026-11-12", "urgent": "true", "lead_days": True},
        {"label": "c", "date": "2026-11-12", "urgent": True, "lead_days": 3, "place": None},
    ]
    out = _plan()
    assert [r.label for r in out] == ["a", "b", "c"]
    assert [r.lead_days for r in out] == [0, 0, 3]  # 숫자가 아닌 값·불리언은 0
    assert [r.urgent for r in out] == [True, False, True]  # True 만 urgent
    assert out[2].place == ""


def test_reply_without_tool_use_gives_empty_list(claude):
    claude.content = [{"type": "text", "text": "챙길 일이 없어요"}]
    assert _plan() == []


def test_http_failure_surfaces_as_llm_unavailable(claude):
    claude.fail = httpx.ConnectError("연결 실패")
    with pytest.raises(LLMUnavailable) as e:
        _plan()
    assert type(e.value) is LLMUnavailable  # 체인이 예외 종류를 바꾸지 않는다
    assert "ConnectError" in str(e.value) and "연결 실패" not in str(e.value)
    assert len(claude.calls) == 1  # 체인에서 따로 재시도하지 않는다


def test_missing_key_surfaces_as_llm_unavailable(claude, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(LLMUnavailable):
        _plan()
    assert claude.calls == []
