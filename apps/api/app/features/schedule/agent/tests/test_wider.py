"""목록이 부족할 때 모델이 기간·키워드를 돌려주면 서버가 이미 읽어 둔 일정 안에서 다시 걸러 한 번 더 묻는지 시험."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.features.schedule import service
from app.features.schedule.agent import handler, period, reader
from app.features.schedule.agent.schemas import AgentRequest
from app.features.schedule.schemas import EventCreate
from app.shared import ai_guard
from app.shared.db import SessionLocal
from app.shared.llm import client as llm

TODAY = date(2026, 10, 28)


def test_from_model_validates_period():
    ok = period.from_model("2026-05-01", "2026-05-31", TODAY)
    assert ok == period.Period(date(2026, 5, 1), date(2026, 5, 31))
    assert period.from_model("어제", "오늘", TODAY) is None  # 형식이 다르다
    assert period.from_model("2026-06-01", "2026-05-01", TODAY) is None  # 순서가 거꾸로
    assert period.from_model("2020-01-01", "2020-02-01", TODAY) is None  # 읽어 둔 범위 밖
    assert period.from_model("2030-01-01", "2030-02-01", TODAY) is None
    clipped = period.from_model("2020-01-01", "2026-11-01", TODAY)
    assert clipped == period.Period(
        TODAY - timedelta(days=365), date(2026, 11, 1)
    )  # 일부만 겹치면 자른다
    assert period.from_model(None, None, TODAY) is None  # type: ignore[arg-type]


@pytest.fixture
def setup(client, family, monkeypatch):
    a, _, group = family
    user_id = client.get("/family-group/me", headers=a).json()["id"]
    group_id = group["id"]
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group_id, user_id, True)
    monkeypatch.setattr(llm, "available", lambda: True)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        for title, days in [("오늘 장보기", 0), ("치과 정기검진", 90), ("멀리 있는 여행", 200)]:
            service.create(
                db,
                group_id,
                user_id,
                EventCreate(title=title, starts_at=now + timedelta(days=days)),
            )
    return user_id, group_id


def _fake(monkeypatch, answers):
    calls = []

    def fake(prompt, schema, system=None, max_tokens=None, **kw):
        calls.append(prompt)
        data = {
            "intent": "query",
            "reply": "",
            "event_ids": [],
            "need_wider": False,
            "period_start": "",
            "period_end": "",
            "keyword": "",
        }
        data.update(answers[min(len(calls), len(answers)) - 1])
        return llm.JsonResult(data=data, input_tokens=1, output_tokens=1, model="fake")

    monkeypatch.setattr(llm, "complete_json", fake)
    return calls


def _ask(setup, text):
    user_id, group_id = setup
    with SessionLocal() as db:
        return handler.handle(db, user_id, group_id, AgentRequest(text=text, channel="personal"))


def test_enough_list_means_one_call(setup, monkeypatch):
    calls = _fake(monkeypatch, [{"reply": "오늘은 장보기가 있어요"}])
    res = _ask(setup, "오늘 일정 알려줘")
    assert len(calls) == 1
    assert res.text == "오늘은 장보기가 있어요"


def test_insufficient_list_asks_again_with_model_keyword(setup, monkeypatch):
    calls = _fake(
        monkeypatch,
        [{"need_wider": True, "keyword": "치과"}, {"reply": "치과 정기검진이 있어요"}],
    )
    res = _ask(setup, "오늘 일정 알려주고 치과도 알려줘")
    assert len(calls) == 2
    assert "치과 정기검진" not in calls[0]  # 첫 호출은 문장의 기간(오늘)만
    assert "치과 정기검진" in calls[1] and "멀리 있는 여행" not in calls[1]  # 키워드로만 거른 목록
    assert "이 목록이 마지막" in calls[1]
    assert res.text == "치과 정기검진이 있어요"


def test_model_period_filters_already_read_events(setup, monkeypatch):
    start = (datetime.now(UTC) + timedelta(days=190)).date().isoformat()
    end = (datetime.now(UTC) + timedelta(days=210)).date().isoformat()
    calls = _fake(
        monkeypatch,
        [
            {"need_wider": True, "period_start": start, "period_end": end},
            {"reply": "여행이 있어요"},
        ],
    )
    _ask(setup, "저번에 말한 여행 언제야")
    assert "멀리 있는 여행" in calls[1]
    assert "치과 정기검진" not in calls[1] and "오늘 장보기" not in calls[1]


def test_invalid_model_period_is_ignored(setup, monkeypatch):
    calls = _fake(
        monkeypatch,
        [
            {"need_wider": True, "period_start": "2001-01-01", "period_end": "2001-02-01"},
            {"reply": "알겠어요"},
        ],
    )
    res = _ask(setup, "저번에 말한 일정 알려줘")
    assert len(calls) == 2
    assert "기간을 알 수 없어" in calls[1]  # 기간을 버리고 가까운 순으로
    assert res.text == "알겠어요"


def test_never_asks_a_third_time(setup, monkeypatch):
    calls = _fake(monkeypatch, [{"need_wider": True, "keyword": "치과"}, {"need_wider": True}])
    res = _ask(setup, "치과 일정 알려줘")
    assert len(calls) == 2
    assert res.text == "해당하는 일정을 찾지 못했어요"


def test_select_by_model_filters_inside_read_events(setup):
    user_id, group_id = setup
    now = datetime.now(UTC)
    with SessionLocal() as db:
        events = reader.read(db, group_id, "personal", now).events
    picked, omitted = reader.select_by_model(events, now, None, " 치 과 ")
    assert [e.title for e in picked] == ["치과 정기검진"] and omitted == 0
    assert len(reader.select_by_model(events, now, None, "")[0]) == 3  # 둘 다 없으면 가까운 순
