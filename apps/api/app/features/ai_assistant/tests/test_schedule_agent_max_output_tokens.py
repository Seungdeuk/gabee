"""일정 Agent 의 출력 토큰 상한(2026-11-25): 1600 → 공통 설정 `settings.agent_max_output_tokens`(기본 10000). 일정 Agent 코드 변경과 같이 움직이는 시험이다.

실제 Anthropic 은 부르지 않는다(가짜 `complete_json`).
"""

import pytest
from sqlalchemy import select

from app.features.family_group.models import User
from app.features.schedule.agent import ask as schedule_ask
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.errors import ApiError
from app.shared.llm import client as llm
from tests.ai_consent import enable_ai, enable_ai_for_user


def _user(db, name="지민"):
    return db.scalars(select(User).where(User.name == name)).first()


@pytest.fixture
def world(client, family, monkeypatch):
    a, _, group = family
    enable_ai(group["id"])
    enable_ai_for_user()
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    return client, a, group


class _FakeSchedule:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append(max_tokens)
        if self.error:
            raise self.error
        return llm.JsonResult(
            data={"intent": "query", "reply": "", "event_ids": []},
            input_tokens=10,
            output_tokens=5,
            model="fake",
        )


def _ask_schedule(group):
    with SessionLocal() as db:
        return schedule_ask.ask(db, group["id"], _user(db), "내일 일정 알려 줘", guarded=False)


def test_the_schedule_agent_requests_the_shared_limit_and_follows_the_override(world, monkeypatch):
    _, _, group = world
    fake = _FakeSchedule()
    monkeypatch.setattr(llm, "complete_json", fake)
    monkeypatch.setattr(llm, "available", lambda: True)
    _ask_schedule(group)
    monkeypatch.setattr(settings, "agent_max_output_tokens", 7777)
    _ask_schedule(group)
    assert fake.calls == [10000, 7777]


def test_a_cut_off_schedule_reply_is_still_a_503_llm_failed(world, monkeypatch):
    """상한을 올려도 잘린 응답(`max_tokens`)의 처리는 그대로다: 503 llm_failed 로 끝나 메인이 오류 결과를 받는다."""
    _, _, group = world
    fake = _FakeSchedule(llm.LLMUnavailable("AI 응답을 쓸 수 없어요 (max_tokens)"))
    monkeypatch.setattr(llm, "complete_json", fake)
    monkeypatch.setattr(llm, "available", lambda: True)
    with pytest.raises(ApiError) as e:
        _ask_schedule(group)
    assert e.value.status == 503 and e.value.code == "llm_failed" and fake.calls == [10000]
