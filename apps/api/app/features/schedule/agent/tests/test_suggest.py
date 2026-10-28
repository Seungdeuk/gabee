"""추천 공급 시험. 실제 Anthropic 은 부르지 않고 llm.complete_json 을 가짜로 바꾼다."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.features.schedule.agent import limits, reader, suggest
from app.features.schedule.constants import SUGGESTION_CONFIRMED, SUGGESTION_PENDING
from app.features.schedule.models import Event, EventSuggestion
from app.shared import ai_guard
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.data: dict = {"suggestions": []}

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append({"prompt": prompt, "model": kw.get("model")})
        return llm.JsonResult(data=self.data, input_tokens=10, output_tokens=5, model="fake")


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(llm, "complete_json", f)
    monkeypatch.setattr(llm, "available", lambda: True)
    # 쿨다운·한도에 걸리지 않게 푼다(한도 자체는 test_limits 에서 본다)
    monkeypatch.setattr(settings, "ai_schedule_card_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "ai_schedule_card_max_calls_per_user_per_day", 100)
    monkeypatch.setattr(settings, "ai_schedule_card_max_calls_per_group_per_day", 100)
    limits.register()
    return f


@pytest.fixture
def ids(client, family):
    a, b, group = family
    user_id = client.get("/family-group/me", headers=a).json()["id"]
    other_id = client.get("/family-group/me", headers=b).json()["id"]
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group["id"], user_id, True)
    return user_id, group["id"], a, other_id


def _day(offset: int) -> str:
    return (reader.to_local(datetime.now(UTC)).date() + timedelta(days=offset)).isoformat()


def _item(title, offset=3, kind=1, place=""):
    return {"title": title, "kind": kind, "date": _day(offset), "place": place}


def _rows(user_id):
    with SessionLocal() as db:
        return list(db.scalars(select(EventSuggestion).where(EventSuggestion.user_id == user_id)))


def _supply(user_id, group_id):
    with SessionLocal() as db:
        items, exhausted = suggest.supply(db, user_id, group_id)
        return [s.title for s in items], exhausted


def _set_status(user_id, status):
    with SessionLocal() as db:
        for s in db.scalars(select(EventSuggestion).where(EventSuggestion.user_id == user_id)):
            s.status = status
        db.commit()


def test_supply_calls_llm_only_without_pending(ids, fake):
    user_id, group_id, *_ = ids
    fake.data = {"suggestions": [_item("약국에서 약 타기"), _item("선물 사기", 5, 2)]}
    first, exhausted = _supply(user_id, group_id)
    assert first == ["약국에서 약 타기", "선물 사기"] and not exhausted
    assert len(fake.calls) == 1 and fake.calls[0]["model"] == suggest.prompts.SUGGEST_MODEL
    assert len({r.created_at for r in _rows(user_id)}) == 1  # 한 묶음 = 같은 시각
    again, _ = _supply(user_id, group_id)
    assert again == first and len(fake.calls) == 1  # 대기가 있으면 호출 없이 그대로


def test_three_batches_then_exhausted(ids, fake):
    user_id, group_id, *_ = ids
    for n in range(3):
        fake.data = {"suggestions": [_item(f"할 일 {n}", n + 1)]}
        assert _supply(user_id, group_id)[0] == [f"할 일 {n}"]
        _set_status(user_id, SUGGESTION_CONFIRMED)  # 대기를 모두 확정해 다음 묶음을 부른다
    assert len(fake.calls) == 3
    assert _supply(user_id, group_id) == ([], True)
    assert len(fake.calls) == 3


def test_new_day_generates_again(ids, fake):
    user_id, group_id, *_ = ids
    fake.data = {"suggestions": [_item("치과 예약", 2)]}
    _supply(user_id, group_id)
    with SessionLocal() as db:  # 어제 만든 것으로 돌린다
        for s in db.scalars(select(EventSuggestion).where(EventSuggestion.user_id == user_id)):
            s.created_at = s.created_at - timedelta(days=1)
        db.commit()
    fake.data = {"suggestions": [_item("장보기", 2)]}
    got, exhausted = _supply(user_id, group_id)
    assert got == ["장보기"] and not exhausted and len(fake.calls) == 2


def test_clean_drops_past_out_of_range_duplicates():
    today = date(2026, 10, 27)

    def it(title, d, **kw):
        return {"title": title, "kind": 1, "date": d, "place": "", **kw}

    data = {
        "suggestions": [
            it("과거", "2026-10-26"),
            it("범위 밖", "2026-12-27"),
            it("날짜 이상", "내일"),
            it("이미 있음", "2026-10-30"),
            it("  새 일정  ", "2026-10-28", kind=9, place="가" * 300),
            it("새 일정", "2026-10-28"),  # 같은 묶음 중복
            it("", "2026-10-29"),
            it("마지막 날", "2026-12-26"),
        ]
    }
    out = suggest.clean_suggestions(data, today, {("이미 있음", date(2026, 10, 30))})
    assert [o["title"] for o in out] == ["새 일정", "마지막 날"]
    assert out[0]["kind"] == 1 and len(out[0]["place"]) == 200
    assert suggest.clean_suggestions("nope", today, set()) == []
    many = {"suggestions": [it(f"t{i}", "2026-10-30") for i in range(9)]}
    assert len(suggest.clean_suggestions(many, today, set())) == 5


def test_existing_event_and_suggestion_are_not_repeated(client, ids, fake):
    user_id, group_id, headers, _ = ids
    client.post("/schedule/events", json={"title": "치과", "start_date": _day(4)}, headers=headers)
    fake.data = {"suggestions": [_item("치과", 4), _item("새 추천", 4)]}
    assert _supply(user_id, group_id)[0] == ["새 추천"]
    assert "치과" in fake.calls[0]["prompt"]
    _set_status(user_id, SUGGESTION_CONFIRMED)  # 확정된 제안과 같은 것도 다시 만들지 않는다
    fake.data = {"suggestions": [_item("새 추천", 4)]}
    assert _supply(user_id, group_id) == ([], False)


def test_get_suggestions_route(client, ids, fake):
    _, _, headers, _ = ids
    fake.data = {"suggestions": [_item("약 타기", 2, 2, "약국")]}
    r = client.get("/schedule/suggestions", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["exhausted"] is False and len(body["suggestions"]) == 1
    s = body["suggestions"][0]
    assert s["title"] == "약 타기" and s["kind"] == 2 and s["place"] == "약국"
    assert s["start_date"] == _day(2) and set(s) == {"id", "title", "kind", "start_date", "place"}
    assert client.get("/schedule/suggestions").status_code in (401, 403)


def test_register_with_suggestion_confirms_it(client, ids, fake):
    user_id, _, headers, other_id = ids
    fake.data = {"suggestions": [_item("선물 사기", 3)]}
    sid = client.get("/schedule/suggestions", headers=headers).json()["suggestions"][0]["id"]
    body = {
        "title": "선물 사기",
        "start_date": _day(3),
        "suggestion_id": sid,
        "share_with": [other_id],
    }
    r = client.post("/schedule/events", json=body, headers=headers)
    assert r.status_code == 201 and "suggestion_id" not in r.json()
    with SessionLocal() as db:
        s = db.get(EventSuggestion, sid)
        assert s.status == SUGGESTION_CONFIRMED and s.confirmed_at is not None
        rows = list(db.scalars(select(Event).where(Event.title == "선물 사기")))
        assert {e.user_id: e.suggestion_id for e in rows} == {user_id: sid, other_id: None}
    # 이미 확정된 제안은 다시 쓸 수 없다
    again = client.post("/schedule/events", json=body, headers=headers)
    assert again.status_code == 400 and "invalid_suggestion" in again.text


def test_register_with_others_or_unknown_suggestion_is_400(client, ids, fake):
    _, group_id, headers, other_id = ids
    with SessionLocal() as db:
        db.add(
            EventSuggestion(
                id="sg-other",
                group_id=group_id,
                user_id=other_id,
                title="남의 추천",
                start_date=date.today(),
                status=SUGGESTION_PENDING,
            )
        )
        db.commit()
    for sid in ("sg-other", "nope"):
        r = client.post(
            "/schedule/events",
            json={"title": "x", "start_date": _day(1), "suggestion_id": sid},
            headers=headers,
        )
        assert r.status_code == 400, r.text
    with SessionLocal() as db:
        assert db.get(EventSuggestion, "sg-other").status == SUGGESTION_PENDING
        assert not list(db.scalars(select(Event).where(Event.title == "x")))


def test_recommend_intent_returns_suggestion_cards(client, ids, monkeypatch, fake):
    _, _, headers, _ = ids
    answers = [
        {"intent": "recommend", "reply": "", "event_ids": []},
        {"suggestions": [_item("약국에서 약 타기", 2)]},
    ]

    def complete(prompt, schema, system=None, max_tokens=None, **kw):
        return llm.JsonResult(data=answers.pop(0), input_tokens=1, output_tokens=1, model="fake")

    monkeypatch.setattr(llm, "complete_json", complete)
    r = client.post(
        "/schedule/agent", json={"text": "일정 추천해줘", "channel": "personal"}, headers=headers
    )
    body = r.json()
    assert body["intent"] == "recommend" and body["text"] == "이런 일정은 어때요?"
    card = body["cards"][0]
    assert card["type"] == "suggestion" and card["data"]["title"] == "약국에서 약 타기"
    assert card["data"]["date"] == _day(2)
    assert set(card["data"]) == {"id", "title", "kind", "date", "place"}
