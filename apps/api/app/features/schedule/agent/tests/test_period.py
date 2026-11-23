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


# 메인 Agent 가 질문을 ISO 날짜(YYYY-MM-DD)가 든 문장으로 바꿔 일정 Agent 에 넘긴다. 예전에는 날짜 뒤의 요일 글자("09-월요일")를
# "9월"로 읽어 기간이 2026-09-01 ~ 2026-11-11 로 틀어졌고, 14·15일 일정이 모델 입력에서 빠졌다(T35 stage A schedq-02).
TUESDAY = date(2026, 11, 10)


@pytest.mark.parametrize(
    "text, start, end",
    [
        (  # 실호출 때 메인이 넘긴 문장 그대로
            "오늘은 2026-11-10(화요일)이야. 이번 주(2026-11-09 월요일부터 2026-11-15 일요일까지) 내 일정을 날짜순으로 알려줘.",
            "2026-11-09",
            "2026-11-15",
        ),
        (
            "이번 주(2026-11-09 월요일부터 2026-11-15 일요일까지) 내 일정을 알려줘",
            "2026-11-09",
            "2026-11-15",
        ),
        ("2026-11-09 월요일부터 2026-11-15 일요일까지", "2026-11-09", "2026-11-15"),
        ("이번 주(2026-11-09부터 2026-11-15까지) 일정 알려줘", "2026-11-09", "2026-11-15"),
        ("2026-11-12 일정", "2026-11-12", "2026-11-12"),  # 예전에는 None
        ("2026-11-12(목요일) 일정", "2026-11-12", "2026-11-12"),
        ("2026-11-14 가족 외식은 몇 시야?", "2026-11-14", "2026-11-14"),
    ],
)
def test_iso_dates_are_read_as_those_days(text, start, end):
    assert period.extract(text, TUESDAY) == Period(
        date.fromisoformat(start), date.fromisoformat(end)
    )


def test_iso_weekday_letters_are_not_read_as_a_month():
    """날짜 뒤에 붙은 요일 글자("월요일")를 N월로 읽어 9월·11월 같은 달 전체가 잡히면 안 된다."""
    got = period.extract("2026-11-09 월요일 일정", TUESDAY)
    assert got == Period(date(2026, 11, 9), date(2026, 11, 9))


@pytest.mark.parametrize("text", ["2026-13-45 일정", "2026-02-30 약속"])
def test_impossible_iso_dates_give_no_period(text):
    assert period.extract(text, TUESDAY) is None  # 없는 날짜는 기간으로 읽지 않는다(넓게 보낸다)


def test_agent_gets_the_family_dinner_and_pending_visit_for_the_rewritten_sentence(
    client, family_ids
):
    """메인이 바꿔 넘긴 문장으로도 그 주의 확정·확정 전 일정이 모델 입력에 모두 들어간다(schedq-02 재현)."""
    user_id, group_id = family_ids
    sentence = (
        "오늘은 2026-11-10(화요일)이야. 이번 주(2026-11-09 월요일부터 2026-11-15 일요일까지) "
        "내 일정을 날짜순으로 알려줘."
    )
    now = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)  # 한국 시간 11월 10일 정오
    with SessionLocal() as db:
        for title, day in [
            ("치과 진료", 11),
            ("학부모 상담", 12),
            ("가족 외식", 14),
            ("할머니 댁 방문", 15),
            ("다음 주 일정", 20),
        ]:
            service.create(
                db,
                group_id,
                user_id,
                EventCreate(title=title, starts_at=datetime(2026, 11, day, 5, 0, tzinfo=UTC)),
            )
        events = reader.read(db, group_id, "personal", now, user_id).events
    local_today = now.astimezone(reader.local_tz()).date()
    shown, _ = reader.select_for_prompt(events, now, period.extract(sentence, local_today))
    titles = [e.title for e in shown]
    assert {"치과 진료", "학부모 상담", "가족 외식", "할머니 댁 방문"} <= set(titles)
    assert "다음 주 일정" not in titles


def test_period_is_widened_by_one_day():
    wide = Period(date(2026, 10, 29), date(2026, 10, 29)).widened()
    assert (wide.start, wide.end) == (date(2026, 10, 28), date(2026, 10, 30))


NOV11 = date(2026, 11, 11)  # 수요일


@pytest.mark.parametrize(
    "text, start, end",
    [
        ("낼 뭐 있어?", "2026-11-12", "2026-11-12"),
        ("낼은 뭐 해?", "2026-11-12", "2026-11-12"),
        ("낼모레 약속", "2026-11-13", "2026-11-13"),
        ("담주 일정 한번에 보여줘", "2026-11-16", "2026-11-22"),
        ("담주 수요일에 병원 예약 잡아줘", "2026-11-18", "2026-11-18"),
        ("병언 예약 잡아줘 담주 수요일 열시에요", "2026-11-18", "2026-11-18"),
        ("담주 화욜 두시에 은행 갔다와야 함", "2026-11-17", "2026-11-17"),
        ("일욜에 뭐 있었나?", "2026-11-15", "2026-11-15"),
        ("담달 일정 알려줘", "2026-12-01", "2026-12-31"),
        (
            "낼 세시에 엄마랑 그거 하기로 했어 아 맞다 엄마 오늘 몇시에 들어오셔?",
            "2026-11-11",
            "2026-11-12",
        ),
    ],
)
def test_colloquial_period_words(text, start, end):
    assert period.extract(text, NOV11) == Period(date.fromisoformat(start), date.fromisoformat(end))


@pytest.mark.parametrize("text", ["보낼 편지 준비", "해낼 수 있어", "이겨낼 거야", "낼름 먹었어"])
def test_slang_does_not_match_inside_other_words(text):
    assert period.extract(text, NOV11) is None


@pytest.mark.parametrize(
    "text, start",
    [
        ("5월 28일에 뭐 했더라?", "2026-05-28"),  # 과거형 → 지난 날짜
        ("5월 28일 저녁에 모임 잡아줘", "2027-05-28"),  # 미래형 → 다가올 날짜
        ("8월에 여행 가자", "2027-08-01"),
        ("10월 3일에 뭐 했지?", "2026-10-03"),
        ("12월 25일 약속 잡아줘", "2026-12-25"),
    ],
)
def test_year_follows_tense(text, start):
    got = period.extract(text, NOV11)
    assert got.start == date.fromisoformat(start) and not got.also and got.note == ""


def test_year_without_tense_picks_nearer_year_with_guide_note():
    march = period.extract("3월 일정 알려줘", NOV11)  # 2027-03 이 더 가깝다
    assert (march.start, march.end) == (date(2027, 3, 1), date(2027, 3, 31))
    assert "2026년 3월이 필요하시면 '올해'" in march.note and not march.also
    sept = period.extract("9월 일정 알려줘", NOV11)  # 2026-09 이 더 가깝다
    assert (sept.start, sept.end) == (date(2026, 9, 1), date(2026, 9, 30))
    assert "2027년 9월이 필요하시면 '내년'" in sept.note


def test_year_without_tense_in_the_middle_sends_both_years():
    got = period.extract("5월 28일 일정 알려줘", NOV11)  # 과거 -167일, 미래 +198일: 중간이라 둘 다
    assert got.start == date(2026, 5, 28) and got.also == ((date(2027, 5, 28), date(2027, 5, 28)),)
    assert got.contains(date(2026, 5, 28)) and got.contains(date(2027, 5, 28))
    assert not got.contains(date(2026, 12, 1))
    wide = got.widened()
    assert wide.contains(date(2027, 5, 29)) and "또는" in wide.label()
    assert "모두 보여 준다" in got.note


def test_select_for_prompt_keeps_events_of_both_years():
    now = datetime(2026, 11, 11, 10, tzinfo=UTC)
    both = period.extract("5월 28일 일정 알려줘", NOV11)

    class E:
        def __init__(self, day):
            self.starts_at = datetime.combine(day, datetime.min.time(), tzinfo=UTC)

    events = [E(date(2026, 5, 28)), E(date(2027, 5, 28)), E(date(2026, 12, 1))]
    shown, omitted = reader.select_for_prompt(events, now, both)
    assert [e.starts_at.date() for e in shown] == [date(2026, 5, 28), date(2027, 5, 28)]
    assert omitted == 0


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


@pytest.mark.parametrize(
    "text",
    [
        "이불 꺼내는 거 담주 월욜로 옮겨줘",
        "가족 나들이 담주로 미뤄줘",
        "은행 방문 25일로 옮길게",
        "화요일 팀회의 열한시로 바꿔줘",
    ],
)
def test_move_sentences_do_not_filter_the_list_by_date(text):
    assert period.extract_for_prompt(text, NOV11) is None  # 옮길 날짜가 대상 일정을 걸러내지 않는다


def test_other_sentences_still_filter_by_date():
    assert period.extract_for_prompt("낼 뭐 있어?", NOV11) == period.extract("낼 뭐 있어?", NOV11)
