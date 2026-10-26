"""문장에서 기간을 뽑는 규칙과, 기간에 맞는 일정만 LLM 에 보내는지 시험."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.features.schedule import service
from app.features.schedule.agent import period, reader
from app.features.schedule.agent.period import Period
from app.features.schedule.schemas import EventCreate
from app.shared import ai_guard
from app.shared.db import SessionLocal
from app.shared.llm import client as llm

TODAY = date(2026, 10, 28)  # 수요일


@pytest.mark.parametrize(
    "text, start, end",
    [
        ("오늘 일정 알려줘", "2026-10-28", "2026-10-28"),
        ("내일 뭐 있어?", "2026-10-29", "2026-10-29"),
        ("모레 약속", "2026-10-30", "2026-10-30"),
        ("이번 주 일정", "2026-10-26", "2026-11-01"),
        ("다음 주 일정 알려줘", "2026-11-02", "2026-11-08"),
        ("다음 주 월요일 약속", "2026-11-02", "2026-11-02"),
        ("지난주 병원", "2026-10-19", "2026-10-25"),
        ("이번 주말에 뭐 해?", "2026-10-31", "2026-11-01"),
        ("금요일 일정", "2026-10-30", "2026-10-30"),
        ("수요일 일정", "2026-10-28", "2026-10-28"),
        ("이번 달 일정", "2026-10-01", "2026-10-31"),
        ("다음 달 일정", "2026-11-01", "2026-11-30"),
        ("12월 일정", "2026-12-01", "2026-12-31"),
        ("11월 3일 일정", "2026-11-03", "2026-11-03"),
        ("1월 5일 약속", "2027-01-05", "2027-01-05"),
        ("내일이랑 모레 일정", "2026-10-29", "2026-10-30"),
        ("내년 일정", "2027-01-01", "2027-12-31"),
    ],
)
def test_extract_period(text, start, end):
    assert period.extract(text, TODAY) == Period(date.fromisoformat(start), date.fromisoformat(end))


@pytest.mark.parametrize(
    "text", ["치과 일정 변경할래", "병원 지워줘", "아빠 생일 추가해줘", "2월 30일", ""]
)
def test_no_period_means_none(text):
    assert period.extract(text, TODAY) is None


def test_period_is_widened_by_one_day():
    wide = Period(date(2026, 10, 29), date(2026, 10, 29)).widened()
    assert (wide.start, wide.end) == (date(2026, 10, 28), date(2026, 10, 30))


def _make(client, family_ids, titles_days):
    user_id, group_id = family_ids
    now = datetime.now(UTC)
    with SessionLocal() as db:
        for title, days in titles_days:
            service.create(
                db,
                group_id,
                user_id,
                EventCreate(title=title, starts_at=now + timedelta(days=days)),
            )
        return reader.read(db, group_id, "personal", now).events, now


@pytest.fixture
def family_ids(client, family):
    a, _, group = family
    return client.get("/family-group/me", headers=a).json()["id"], group["id"]


def test_select_with_period_sends_only_that_period(client, family_ids):
    events, now = _make(
        client, family_ids, [("오늘", 0), ("내일", 1), ("일주일 뒤", 7), ("두 달 뒤", 60)]
    )
    local_today = now.astimezone(reader.local_tz()).date()
    picked, omitted = reader.select_for_prompt(events, now, Period(local_today, local_today))
    titles = [e.title for e in picked]
    assert "오늘" in titles and "내일" in titles  # 앞뒤 하루 여유
    assert "일주일 뒤" not in titles and "두 달 뒤" not in titles
    assert omitted == 0


def test_agent_sends_only_period_events_titles_only(client, family_ids, monkeypatch):
    user_id, group_id = family_ids
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group_id, user_id, True)
    calls = []

    def fake(prompt, schema, system=None, max_tokens=None, **kw):
        calls.append(prompt)
        return llm.JsonResult(
            data={"intent": "query", "reply": "", "event_ids": []},
            input_tokens=1,
            output_tokens=1,
            model="fake",
        )

    monkeypatch.setattr(llm, "complete_json", fake)
    monkeypatch.setattr(llm, "available", lambda: True)
    from app.features.schedule.agent import handler
    from app.features.schedule.agent.schemas import AgentRequest

    now = datetime.now(UTC)
    with SessionLocal() as db:
        for title, days, note in [("오늘 치과", 0, "메모비밀"), ("멀리 있는 일정", 100, "x")]:
            service.create(
                db,
                group_id,
                user_id,
                EventCreate(title=title, starts_at=now + timedelta(days=days), note=note),
            )
        handler.handle(
            db, user_id, group_id, AgentRequest(text="오늘 일정 알려줘", channel="personal")
        )
        handler.handle(
            db, user_id, group_id, AgentRequest(text="치과 일정 변경할래", channel="personal")
        )
    assert "오늘 치과" in calls[0] and "멀리 있는 일정" not in calls[0]
    assert "메모비밀" not in calls[0]  # 메모는 보내지 않는다
    assert "문장에서 읽은 기간" in calls[0]
    assert "오늘 치과" in calls[1] and "멀리 있는 일정" in calls[1]  # 기간이 없으면 넓게(1년 안)
    assert "기간을 알 수 없어" in calls[1]
