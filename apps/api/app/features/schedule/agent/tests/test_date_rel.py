"""상대 날짜 표현(date_rel) 계산 시험. 모델이 날짜를 직접 계산하지 않고 weeks·days·weekday 만 돌려주면
코드가 기준 날짜로 YYYY-MM-DD 를 만든다(등록=오늘, 수정=일정의 원래 날짜 또는 오늘). 모델 응답은 가짜로 바꾼다."""

from datetime import date, timedelta

import pytest

from app.features.schedule.agent import modify, register
from app.shared import ai_guard
from app.shared.db import SessionLocal
from app.shared.llm import client as llm


def _rel(weeks=0, days=0, weekday=-1):
    return {"weeks": weeks, "days": days, "weekday": weekday}


# ---------- resolve_date ----------
def test_next_week_keeps_same_weekday():
    assert (
        register.resolve_date(date(2026, 11, 22), _rel(weeks=1)) == "2026-11-29"
    )  # 일 → 다음 주 일


def test_days_and_month_year_rollover():
    assert register.resolve_date(date(2026, 11, 29), _rel(days=2)) == "2026-12-01"
    assert register.resolve_date(date(2026, 12, 28), _rel(weeks=1)) == "2027-01-04"


def test_weekday_is_relative_to_monday_of_base_week():
    # 2026-11-22 는 일요일: 그 주 월요일은 11/16. 다음 주 금요일 = 11/27 + 7
    assert register.resolve_date(date(2026, 11, 22), _rel(weeks=1, weekday=4)) == "2026-11-27"
    assert register.resolve_date(date(2026, 11, 20), _rel(weekday=0)) == "2026-11-16"
    assert (
        register.resolve_date(date(2026, 11, 20), _rel(weeks=1, days=1, weekday=6)) == "2026-11-30"
    )


@pytest.mark.parametrize(
    "rel",
    [
        _rel(weeks=105),
        _rel(weeks=-105),
        _rel(weekday=7),
        _rel(weekday=-2),
        _rel(weeks=True),
        _rel(weeks=1.0),
        _rel(weeks="1"),
        {"weeks": 1},
        None,
    ],
)
def test_out_of_range_or_bad_values_give_empty(rel):
    assert register.resolve_date(date(2026, 11, 22), rel) == ""


def test_result_must_pass_valid_date_range():
    assert register.resolve_date(date(2026, 11, 22), _rel(weeks=104)) == "2028-11-19"  # 728일
    assert register.resolve_date(date(2026, 11, 22), _rel(weeks=104, days=5)) == ""  # 733일


def test_clean_rel_defaults_and_has_rel():
    assert register.clean_rel(None) == register.NO_REL
    assert register.clean_rel({"weeks": "1", "days": 0, "weekday": -1}) == register.NO_REL
    assert register.clean_rel(_rel(weeks=1)) == _rel(weeks=1)
    assert not register.has_rel(register.NO_REL) and register.has_rel(_rel(days=2))
    assert register.clean_fields({}, set())["date_rel"] == register.NO_REL
    assert modify.clean_changes({})["date_rel"] == register.NO_REL


# ---------- 흐름 ----------
class FakeLLM:
    def __init__(self):
        self.data = {}

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        return llm.JsonResult(data=self.data, input_tokens=100, output_tokens=20, model="fake")


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(llm, "complete_json", f)
    monkeypatch.setattr(llm, "available", lambda: True)
    return f


@pytest.fixture
def setup(client, family):
    a, _, group = family
    me = client.get("/family-group/me", headers=a).json()["id"]
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group["id"], me, True)
    return a


def _say(client, headers, text):
    return client.post(
        "/schedule/agent", json={"text": text, "channel": "personal"}, headers=headers
    )


def _events(client, headers):
    return client.get("/schedule/events", params={"include_past": True}, headers=headers).json()


def _register_data(**fields):
    base = {
        "title": "",
        "date": "",
        "start_time": "",
        "end_time": "",
        "kind": 0,
        "place": "",
        "memo": "",
        "share_ids": [],
        "date_ambiguous": False,
    }
    base.update(fields)
    return {"intent": "register", "reply": "", "event_ids": [], "register": base}


def _edit_data(target, **changes):
    base = {
        "title": "",
        "date": "",
        "start_time": "",
        "end_time": "",
        "kind": 0,
        "place": "",
        "memo": "",
        "clear": [],
        "share_change": False,
        "share_ids": [],
    }
    base.update(changes)
    return {"intent": "edit", "reply": "", "event_ids": [], "target_id": target, "changes": base}


def _new_event(client, headers, day: date):
    r = client.post(
        "/schedule/events",
        json={"title": "치과", "start_date": day.isoformat(), "start_time": "14:00:00"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_register_with_date_rel_is_computed_from_today(client, setup, fake):
    a = setup
    fake.data = _register_data(title="병원", date_rel=_rel(days=2))
    body = _say(client, a, "이틀 뒤에 병원 등록해줘").json()
    expected = (register.today() + timedelta(days=2)).isoformat()
    assert body["cards"][0]["data"]["date"] == expected
    assert _events(client, a)[0]["start_date"] == expected


def test_register_concrete_date_wins_over_date_rel(client, setup, fake):
    a = setup
    day = (register.today() + timedelta(days=3)).isoformat()
    fake.data = _register_data(title="병원", date=day, date_rel=_rel(weeks=1))
    body = _say(client, a, "병원 등록해줘").json()
    assert body["cards"][0]["data"]["date"] == day


def test_edit_next_week_moves_same_weekday_from_event_date(client, setup, fake):
    a = setup
    original = register.today() + timedelta(days=2)
    event_id = _new_event(client, a, original)
    fake.data = _edit_data(event_id, date_rel=_rel(weeks=1))
    body = _say(client, a, "치과 담주로 미뤄줘").json()
    expected = (original + timedelta(days=7)).isoformat()
    assert "바꿨어요" in body["text"], body
    assert _events(client, a)[0]["start_date"] == expected
    assert (original + timedelta(days=7)).weekday() == original.weekday()


def test_edit_weekday_is_relative_to_today(client, setup, fake):
    a = setup
    event_id = _new_event(client, a, register.today() + timedelta(days=2))
    fake.data = _edit_data(event_id, date_rel=_rel(weeks=1, weekday=4))
    _say(client, a, "치과 다음 주 금요일로 옮겨줘")
    today = register.today()
    expected = today - timedelta(days=today.weekday()) + timedelta(days=7 + 4)
    assert _events(client, a)[0]["start_date"] == expected.isoformat()


def test_edit_concrete_date_wins_over_date_rel(client, setup, fake):
    a = setup
    event_id = _new_event(client, a, register.today() + timedelta(days=2))
    day = (register.today() + timedelta(days=5)).isoformat()
    fake.data = _edit_data(event_id, date=day, date_rel=_rel(weeks=1))
    _say(client, a, "치과 날짜 바꿔줘")
    assert _events(client, a)[0]["start_date"] == day
