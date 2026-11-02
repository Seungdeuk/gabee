"""추천 공급 시험. 실제 Anthropic 은 부르지 않고 llm.complete_json 을 가짜로 바꾼다."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.features.schedule.agent import limits, reader, suggest, suggest_sources
from app.features.schedule.constants import (
    SUGGESTION_CONFIRMED,
    SUGGESTION_DISMISSED,
    SUGGESTION_PENDING,
)
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
    # 참고할 데이터가 하나도 없으면 AI 를 부르지 않으므로, 기본으로 개인 채팅 한 줄을 깐다(f.seed=False 로 끈다)
    f.seed = True
    collect = suggest_sources.collect

    def seeded(*args, **kw):
        sources = collect(*args, **kw)
        if f.seed and not sources.chat:
            sources.chat = ["이번 주에 할 일을 정리하고 싶어"]
        return sources

    monkeypatch.setattr(suggest_sources, "collect", seeded)
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
    # 새로고침마다 섞이므로 순서는 비교하지 않는다
    assert sorted(again) == sorted(first) and len(fake.calls) == 1  # 대기가 있으면 호출 없이 그대로


def test_three_batches_then_exhausted(ids, fake, monkeypatch):
    user_id, group_id, *_ = ids
    monkeypatch.setattr(settings, "ai_schedule_card_max_calls_per_user_per_day", 3)
    limits.register()
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
    assert s["start_date"] == _day(2) and set(s) == {
        "id",
        "title",
        "kind",
        "start_date",
        "place",
        "later",
    }
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


def test_recommend_intent_says_not_found_when_calls_spent_without_any_suggestion(
    client, ids, monkeypatch, fake
):
    _, _, headers, _ = ids
    _limit(monkeypatch, 0)  # 추천 카드 호출을 다 쓴 상태인데 오늘 받은 추천은 하나도 없다
    fake.data = {"intent": "recommend", "reply": "", "event_ids": []}
    r = client.post(
        "/schedule/agent", json={"text": "일정 추천해줘", "channel": "personal"}, headers=headers
    )
    body = r.json()
    assert body["intent"] == "recommend" and body["cards"] == []
    assert (
        body["text"] == "일정을 찾지 못했어요. 내일 다시 찾아볼게요😢"
    )  # 마무리 인사(💛)가 아니다


# ---------- 추천 카드 슬롯: 상태별 동작 ----------
def _slot(user_id, group_id):
    with SessionLocal() as db:
        slot = suggest.supply_slot(db, user_id, group_id)
        return sorted(s.title for s in slot.items), slot.state, slot.can_refresh


def _limit(monkeypatch, per_user):
    monkeypatch.setattr(settings, "ai_schedule_card_max_calls_per_user_per_day", per_user)
    limits.register()


def _mark(user_id, title, status):
    with SessionLocal() as db:
        for s in db.scalars(select(EventSuggestion).where(EventSuggestion.user_id == user_id)):
            if s.title == title:
                s.status = status
        db.commit()


def test_pending_is_shown_shuffled_without_calling(ids, fake, monkeypatch):
    user_id, group_id, *_ = ids
    fake.data = {"suggestions": [_item("가", 1), _item("나", 2), _item("다", 3)]}
    _supply(user_id, group_id)
    monkeypatch.setattr(suggest.random, "shuffle", lambda rows: rows.reverse())
    with SessionLocal() as db:
        slot = suggest.supply_slot(db, user_id, group_id)
    assert [s.title for s in slot.items] == ["다", "나", "가"] and slot.state == "ok"
    assert len(fake.calls) == 1  # 한도가 남아도 대기가 있으면 부르지 않는다


def test_past_dated_pending_is_not_shown(ids, fake):
    user_id, group_id, *_ = ids
    fake.data = {"suggestions": [_item("지난 일", 1), _item("앞으로", 2)]}
    _supply(user_id, group_id)
    with SessionLocal() as db:
        s = db.scalars(select(EventSuggestion).where(EventSuggestion.title == "지난 일")).one()
        s.start_date = s.start_date - timedelta(days=5)
        db.commit()
    assert _slot(user_id, group_id)[0] == ["앞으로"]


def test_only_later_with_calls_left_calls_again(ids, fake):
    user_id, group_id, *_ = ids
    fake.data = {"suggestions": [_item("미룬 일", 2)]}
    _supply(user_id, group_id)
    _mark(user_id, "미룬 일", SUGGESTION_DISMISSED)
    fake.data = {
        "suggestions": [_item("미룬 일", 2), _item("새 일", 3)]
    }  # 나중에 한 것과 같은 건 만들지 않는다
    assert _slot(user_id, group_id) == (["새 일"], "ok", True)
    assert len(fake.calls) == 2
    assert "미룬 일" in fake.calls[1]["prompt"]


def test_calls_spent_keeps_showing_later_then_exhausted(ids, fake, monkeypatch):
    user_id, group_id, *_ = ids
    _limit(monkeypatch, 1)
    fake.data = {"suggestions": [_item("가", 1), _item("나", 2)]}
    _supply(user_id, group_id)
    _mark(user_id, "가", SUGGESTION_DISMISSED)
    _mark(user_id, "나", SUGGESTION_DISMISSED)
    for _ in range(3):  # 새로고침해도 호출 없이 계속 보인다
        assert _slot(user_id, group_id) == (["가", "나"], "ok", False)
    assert len(fake.calls) == 1
    _mark(user_id, "가", SUGGESTION_CONFIRMED)
    _mark(user_id, "나", SUGGESTION_CONFIRMED)
    assert _slot(user_id, group_id) == ([], "exhausted", False)


def test_no_data_does_not_call_or_spend(ids, fake):
    user_id, group_id, *_ = ids
    fake.seed = False
    with SessionLocal() as db:
        before = ai_guard.calls_left(db, user_id, group_id, suggest.FEATURE)
    assert _slot(user_id, group_id) == ([], "no_data", True)
    assert not fake.calls
    with SessionLocal() as db:
        assert ai_guard.calls_left(db, user_id, group_id, suggest.FEATURE) == before


def test_filtered_result_counts_as_a_call(ids, fake, monkeypatch):
    user_id, group_id, *_ = ids
    _limit(monkeypatch, 2)
    fake.data = {"suggestions": [_item("범위 밖", 90)]}  # 날짜 범위 밖이라 전부 걸러진다
    assert _slot(user_id, group_id) == ([], "filtered", True)
    # 둘째 호출로 한도를 다 썼는데 오늘 받은 추천이 하나도 없으면 마무리 인사(exhausted)가 아니라 못 찾았다고 알린다
    assert _slot(user_id, group_id) == ([], "spent_empty", False)
    assert len(fake.calls) == 2 and not _rows(user_id)


def test_spent_with_only_past_dated_suggestions_counts_as_none_received(ids, fake, monkeypatch):
    # 오늘 만든 추천이 있어도 날짜가 이미 지나 보여 줄 수 없게 됐으면 "받은 추천 없음"으로 본다(마무리 인사가 아니라 못 찾았다고 알림)
    user_id, group_id, *_ = ids
    _limit(monkeypatch, 1)
    fake.data = {"suggestions": [_item("지난 일정", 1)]}
    assert _slot(user_id, group_id) == (["지난 일정"], "ok", True)
    _mark(user_id, "지난 일정", SUGGESTION_CONFIRMED)
    with SessionLocal() as db:
        for s in db.scalars(select(EventSuggestion).where(EventSuggestion.user_id == user_id)):
            s.start_date = s.start_date - timedelta(days=30)
        db.commit()
    assert _slot(user_id, group_id) == ([], "spent_empty", False)


def test_error_after_all_confirmed_shows_preparing_then_exhausted_when_spent(
    ids, fake, monkeypatch
):
    # 한 번 성공해 받은 추천을 전부 확정한 뒤 호출이 계속 실패하면: 한도가 남은 동안은 준비 중, 다 쓰면 오늘은 여기까지
    user_id, group_id, *_ = ids
    _limit(monkeypatch, 3)
    fake.data = {"suggestions": [_item("가", 2)]}
    assert _slot(user_id, group_id) == (["가"], "ok", True)
    _mark(user_id, "가", SUGGESTION_CONFIRMED)

    def boom(*a, **kw):
        raise llm.LLMUnavailable("실패")

    monkeypatch.setattr(llm, "complete_json", boom)
    assert _slot(user_id, group_id) == ([], "preparing", True)  # 둘째 호출 실패
    assert _slot(user_id, group_id) == ([], "preparing", True)  # 셋째 호출 실패(마지막 한 번)
    assert _slot(user_id, group_id) == ([], "exhausted", False)  # 한도를 다 썼으니 마무리 인사


def test_error_shows_preparing_or_falls_back_to_later(ids, fake, monkeypatch):
    user_id, group_id, *_ = ids
    fake.data = {"suggestions": [_item("미룬 일", 2)]}
    _supply(user_id, group_id)
    _mark(user_id, "미룬 일", SUGGESTION_DISMISSED)

    def boom(*a, **kw):
        raise llm.LLMUnavailable("실패")

    monkeypatch.setattr(llm, "complete_json", boom)
    assert _slot(user_id, group_id) == (
        ["미룬 일"],
        "ok",
        True,
    )  # 나중에 한 게 있으면 그걸 보여준다
    _mark(user_id, "미룬 일", SUGGESTION_CONFIRMED)
    assert _slot(user_id, group_id) == ([], "preparing", True)


def test_ai_off_shows_preparing_without_refresh(ids, fake):
    user_id, group_id, *_ = ids
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group_id, user_id, False)
    assert _slot(user_id, group_id) == ([], "preparing", False)
    assert not fake.calls


def test_daily_limit_error_means_exhausted(ids, fake, monkeypatch):
    user_id, group_id, *_ = ids
    _limit(monkeypatch, 0)  # 가드는 한도로 막는데
    monkeypatch.setattr(ai_guard, "calls_left", lambda *a, **kw: 1)  # 남은 횟수 계산은 통과한 경우
    assert _slot(user_id, group_id) == (
        [],
        "spent_empty",
        False,
    )  # 오늘 받은 추천이 없으니 마무리 인사가 아니다
    assert not fake.calls


def test_set_later_route(client, ids, fake):
    user_id, _, headers, _ = ids
    fake.data = {"suggestions": [_item("할 일", 2)]}
    sid = client.get("/schedule/suggestions", headers=headers).json()["suggestions"][0]["id"]
    r = client.put(f"/schedule/suggestions/{sid}/later", json={"later": True}, headers=headers)
    assert r.status_code == 200 and r.json()["later"] is True
    with SessionLocal() as db:
        assert db.get(EventSuggestion, sid).status == SUGGESTION_DISMISSED
    r = client.put(f"/schedule/suggestions/{sid}/later", json={"later": False}, headers=headers)
    assert r.json()["later"] is False
    with SessionLocal() as db:
        assert db.get(EventSuggestion, sid).status == SUGGESTION_PENDING
    body = client.get("/schedule/suggestions", headers=headers).json()
    assert body["state"] == "ok" and body["can_refresh"] is True and not body["exhausted"]
    assert body["suggestions"][0]["later"] is False
    _mark(user_id, "할 일", SUGGESTION_CONFIRMED)  # 확정된 건 바꿀 수 없다
    r = client.put(f"/schedule/suggestions/{sid}/later", json={"later": True}, headers=headers)
    assert r.status_code == 400 and "invalid_suggestion" in r.text
    r = client.put("/schedule/suggestions/nope/later", json={"later": True}, headers=headers)
    assert r.status_code == 400


def test_set_later_rejects_other_users_suggestion(client, ids, fake):
    _, group_id, headers, other_id = ids
    with SessionLocal() as db:
        db.add(
            EventSuggestion(
                id="sg-other2",
                group_id=group_id,
                user_id=other_id,
                title="남의 추천",
                start_date=date.today(),
            )
        )
        db.commit()
    r = client.put("/schedule/suggestions/sg-other2/later", json={"later": True}, headers=headers)
    assert r.status_code == 400
    with SessionLocal() as db:
        assert db.get(EventSuggestion, "sg-other2").status == SUGGESTION_PENDING
