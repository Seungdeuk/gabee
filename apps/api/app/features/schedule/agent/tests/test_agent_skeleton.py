"""일정 에이전트 뼈대 시험. 실제 Anthropic 은 부르지 않고 llm.complete_json 을 가짜로 바꾼다."""

from datetime import UTC, datetime, timedelta

import pytest

from app.features.schedule import service
from app.features.schedule.agent import handler, intent, prompts, reader
from app.features.schedule.agent.schemas import AgentRequest
from app.features.schedule.schemas import EventCreate
from app.shared import ai_guard
from app.shared.db import SessionLocal
from app.shared.errors import ApiError
from app.shared.llm import client as llm


class FakeLLM:
    def __init__(self, intent_value="query"):
        self.calls = []
        self.intent_value = intent_value

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append({"prompt": prompt, "model": kw.get("model")})
        return llm.JsonResult(
            data={"intent": self.intent_value}, input_tokens=10, output_tokens=2, model="fake"
        )


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(llm, "complete_json", f)
    monkeypatch.setattr(llm, "available", lambda: True)
    return f


def _ids(client, family):
    a, _, group = family
    me = client.get("/family-group/me", headers=a).json()
    return me["id"], group["id"]


def _enable(user_id, group_id):
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group_id, user_id, True)


def test_clean_intent_falls_back_to_not_schedule():
    assert intent.clean_intent({"intent": "register"}) == "register"
    assert intent.clean_intent({"intent": "delete_everything"}) == "not_schedule"
    assert intent.clean_intent({}) == "not_schedule"
    assert intent.clean_intent("x") == "not_schedule"  # type: ignore[arg-type]


def test_family_channel_does_not_read_personal_chat():
    assert "personal_chat" in reader.allowed_sources("personal")
    assert "family_chat" in reader.allowed_sources("personal")
    assert "personal_chat" not in reader.allowed_sources("family")
    assert "schedule" in reader.allowed_sources("family")


def test_read_covers_one_year_each_way(client, family):
    user_id, group_id = _ids(client, family)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        for title, delta in [
            ("작년 초", -400),
            ("지난달", -30),
            ("다음 달", 30),
            ("재작년 뒤", 400),
        ]:
            service.create(
                db,
                group_id,
                user_id,
                EventCreate(title=title, starts_at=now + timedelta(days=delta)),
            )
        titles = [e.title for e in reader.read(db, group_id, "personal", now).events]
    assert titles == ["지난달", "다음 달"]


def test_window_keeps_only_asked_range(client, family):
    user_id, group_id = _ids(client, family)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        for title, delta in [("오늘", 0), ("내일", 1), ("다음 주", 8)]:
            service.create(
                db,
                group_id,
                user_id,
                EventCreate(title=title, starts_at=now + timedelta(days=delta)),
            )
        events = reader.read(db, group_id, "personal", now).events
    picked = reader.window(events, now - timedelta(hours=1), now + timedelta(days=2))
    assert [e.title for e in picked] == ["오늘", "내일"]


def test_classify_uses_intent_model_and_caches(client, family, fake):
    user_id, group_id = _ids(client, family)
    _enable(user_id, group_id)
    with SessionLocal() as db:
        assert intent.classify(db, user_id, group_id, "이번 주 일정 알려줘") == "query"
        assert intent.classify(db, user_id, group_id, "이번 주 일정 알려줘") == "query"
    assert len(fake.calls) == 1  # 같은 문장은 캐시
    assert fake.calls[0]["model"] == prompts.INTENT_MODEL


def test_handle_returns_not_schedule_for_general_question(client, family, fake):
    fake.intent_value = "not_schedule"
    user_id, group_id = _ids(client, family)
    _enable(user_id, group_id)
    with SessionLocal() as db:
        res = handler.handle(
            db, user_id, group_id, AgentRequest(text="오늘 날씨 어때?", channel="family")
        )
    assert res.intent == "not_schedule"
    assert res.cards == [] and res.pending_action is None


def test_handle_rejects_non_member(client, family, fake):
    _, group_id = _ids(client, family)
    with SessionLocal() as db:
        with pytest.raises(ApiError) as e:
            handler.handle(
                db, "nobody", group_id, AgentRequest(text="일정 알려줘", channel="personal")
            )
    assert e.value.code == "not_member"


def test_handle_requires_ai_consent(client, family, fake):
    user_id, group_id = _ids(client, family)
    with SessionLocal() as db:
        with pytest.raises(ApiError) as e:
            handler.handle(
                db, user_id, group_id, AgentRequest(text="일정 알려줘", channel="personal")
            )
    assert e.value.code == "ai_not_enabled"
    assert fake.calls == []
