"""골든벨 가비 추천: 재료(공동 일정·가족 전체방 대화), 정답 검증, 하루 캐시, 상태. 실제 AI 는 부르지 않고 llm.complete_json 을 가짜로 바꾼다."""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.features.play import quiz_rec
from app.features.play.models import PlayQuiz
from app.features.play.rec_pick import pick_for_user
from app.features.schedule.models import Event
from app.shared import ai_guard
from app.shared.ai_usage import AiResultCache
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm

REC = "/play/quiz/recommendations"
TODAY = datetime.now(UTC).astimezone(quiz_rec.local_tz()).date()
DAY = TODAY + timedelta(days=3)


# ---------- 검증 단위 ----------
def ev(title, place="", memo="", day=DAY):
    return Event(id="e", group_id="g", title=title, place=place, memo=memo, start_date=day)


def q(**kw):
    base = {
        "kind": "choice",
        "question": "여행지는 어디였을까?",
        "options": ["제주도", "강릉", "부산"],
        "answer_index": 0,
        "source": "schedule",
        "source_no": 1,
        "evidence": "제주도",
    }
    return {**base, **kw}


def clean(items, events=None, chat=None, used=None):
    events = events if events is not None else [ev("가족 여행", place="제주도")]
    return quiz_rec.clean_questions({"questions": items}, events, chat or {}, used or set())


def test_schedule_choice_answer_must_be_in_event_data():
    assert len(clean([q()])) == 1
    assert (
        clean([q(options=["강릉", "제주도", "부산"], answer_index=0)]) == []
    )  # 정답이 일정에 없다
    assert clean([q(evidence="한라산")]) == []  # 근거가 일정에 없다
    assert clean([q(source_no=2)]) == []  # 없는 일정 번호


def test_schedule_evidence_joined_by_separators_is_accepted():
    # 모델이 근거를 "제목 / 장소"처럼 이어 돌려줘도 조각마다 일정 데이터에 있으면 인정한다
    assert len(clean([q(evidence="가족 여행 / 제주도")])) == 1
    assert len(clean([q(evidence="가족 여행, 제주도")])) == 1
    assert clean([q(evidence="가족 여행 / 한라산")]) == []  # 한 조각이라도 일정에 없으면 버린다
    assert clean([q(evidence=" / ")]) == []  # 빈 근거


def test_birthday_date_choice_matches_event_date():
    events = [ev("엄마 생신", day=date(2026, 12, 5))]
    ok = q(
        question="엄마 생신은 몇 월일까?",
        options=["11월", "12월", "1월"],
        answer_index=1,
        evidence="엄마 생신",
    )
    bad = q(
        question="엄마 생신은 몇 월일까?",
        options=["11월", "12월", "1월"],
        answer_index=0,
        evidence="엄마 생신",
    )
    assert len(clean([ok], events)) == 1
    assert clean([bad], events) == []


def test_day_only_choice_matches_event_day():
    events = [ev("엄마 생신", day=date(2026, 12, 5))]
    ask = dict(question="엄마 생신은 며칠일까?", evidence="엄마 생신")
    assert len(clean([q(**ask, options=["3일", "5일", "9일"], answer_index=1)], events)) == 1
    assert clean([q(**ask, options=["3일", "5일", "9일"], answer_index=0)], events) == []
    # 날짜를 묻는 말이 없으면 "5일"은 일정 글자에서 찾는다(없으면 버림)
    other = dict(question="여행은 몇 박일까?", evidence="엄마 생신")
    assert clean([q(**other, options=["3일", "5일", "9일"], answer_index=1)], events) == []


def test_ox_date_statement_must_agree_with_answer():
    events = [ev("엄마 생신", day=date(2026, 12, 5))]
    right = q(
        kind="ox",
        question="엄마 생신은 12월이다",
        options=["O", "X"],
        answer_index=0,
        evidence="엄마 생신",
    )
    wrong = q(
        kind="ox",
        question="엄마 생신은 11월이다",
        options=["O", "X"],
        answer_index=0,
        evidence="엄마 생신",
    )
    false_ok = q(
        kind="ox",
        question="엄마 생신은 11월이다",
        options=["O", "X"],
        answer_index=1,
        evidence="엄마 생신",
    )
    assert len(clean([right], events)) == 1
    assert clean([wrong], events) == []
    assert len(clean([false_ok], events)) == 1


def test_chat_question_needs_evidence_in_the_message():
    chat = {7: "토요일에 부산 해운대에서 회 먹기로 했어요"}
    ok = q(
        source="chat", source_no=7, evidence="부산 해운대", options=["부산 해운대", "강릉", "속초"]
    )
    assert len(clean([ok], chat=chat)) == 1
    assert clean([{**ok, "evidence": "제주 한라산"}], chat=chat) == []  # 대화에 없는 근거
    assert clean([{**ok, "source_no": 8}], chat=chat) == []  # 없는 메시지
    assert clean([{**ok, "options": ["강릉", "속초", "양양"]}], chat=chat) == []  # 정답이 근거 밖


def test_tokens_shapes_and_duplicates_are_dropped():
    assert clean([q(question="[PERSON_1]가 간 여행지는?")]) == []
    assert clean([q(options=["제주도", "강릉"])]) == []  # 선택 보기는 3~4개
    assert clean([q(options=["제주도", "제주도", "부산"])]) == []
    assert clean([q(options=["제주도", "강릉", "x" * 21])]) == []
    assert clean([q(kind="ox", options=["O", "X"], answer_index=2)]) == []
    assert clean([q(question="가" * 61)]) == []
    assert clean([q(), q()]) and len(clean([q(), q()])) == 1  # 같은 질문은 한 번만
    assert clean([q()], used={quiz_rec._norm("여행지는 어디였을까?")}) == []  # 이미 낸 문제


def test_at_most_seven_questions():
    events = [ev(f"여행 {i}", place=f"장소{i}") for i in range(10)]
    items = [
        q(
            question=f"{i}번째 여행지는?",
            options=[f"장소{i}", "가", "나"],
            evidence=f"장소{i}",
            source_no=i + 1,
        )
        for i in range(10)
    ]
    assert len(clean(items, events)) == quiz_rec.SHOW_MAX == 7


# ---------- API ----------
class FakeLLM:
    def __init__(self):
        self.calls = []
        self.data = None
        self.error = None

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append({"prompt": prompt, "system": system, "max_tokens": max_tokens})
        if self.error is not None:
            raise self.error
        return llm.JsonResult(data=self.data, input_tokens=100, output_tokens=50, model="fake")


@pytest.fixture(autouse=True)
def loose_limits():
    ai_guard.register_bucket(quiz_rec.FEATURE, ai_guard.Limits(0, 100, 100), (quiz_rec.FEATURE,))
    yield
    quiz_rec.register_limits()


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(llm, "complete_json", f)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    return f


def me(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def add_event(client, headers, **fields):
    body = {"title": "가족 여행", "start_date": DAY.isoformat(), "place": "제주도", **fields}
    r = client.post("/schedule/events", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def say(client, headers, text):
    r = client.post("/family-chat/messages", json={"text": text}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def enable_ai(client, headers):
    r = client.put("/family-chat/ai/settings", json={"enabled": True}, headers=headers)
    assert r.status_code == 200, r.text


def good():
    return {"questions": [q()]}


@pytest.fixture
def ready(client, family, fake):
    """AI 를 켠 가족과 공유 일정 하나(수진과 공유). (a, b, group)."""
    a, b, group = family
    enable_ai(client, a)
    add_event(client, a, share_with=[me(client, b)])
    fake.data = good()
    return a, b, group


def get(client, headers):
    r = client.get(REC, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_returns_questions_and_caches_for_the_day(client, ready, fake):
    a, b, _ = ready
    first = get(client, a)
    assert first["state"] == "ok"
    assert [i["question"] for i in first["items"]] == ["여행지는 어디였을까?"]
    assert first["items"][0]["source"] == "schedule"
    # 같은 가족은 누가 열어도 같은 묶음, AI 는 한 번만 불렸다
    assert get(client, b) == first
    assert get(client, a) == first
    assert len(fake.calls) == 1
    with SessionLocal() as db:
        row = db.scalar(select(AiResultCache).where(AiResultCache.feature == quiz_rec.FEATURE))
        now = datetime.now(UTC)
        expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
        assert expires == quiz_rec.local_day_start(now) + timedelta(
            days=1
        )  # 기본 10분이 아니라 당일 자정까지


def test_prompt_has_shared_event_only_and_asks_for_eight(client, ready, fake):
    a, _, _ = ready
    add_event(client, a, title="혼자 일정", place="비밀장소")  # 공유하지 않은 내 일정
    get(client, a)
    prompt = fake.calls[0]["prompt"]
    assert "가족 여행" in prompt and "제주도" in prompt
    assert "혼자 일정" not in prompt and "비밀장소" not in prompt
    assert "일정에서 7개 이하" in prompt  # 일정만 있으면 일정에서 모두 만든다
    assert "경조사" in fake.calls[0]["system"]
    # 모델의 생각 토큰이 출력 한도를 같이 써서 작은 한도로는 답이 나오기 전에 잘린다(실제 대화로 3000 에서 실패를 확인함)
    assert fake.calls[0]["max_tokens"] >= 8000


def test_chat_questions_come_from_family_room(client, ready, fake):
    a, b, _ = ready
    say(client, a, "다음 주에 부산 해운대에서 회 먹자")
    say(client, b, "좋아 해운대 가자")
    ids = [say(client, a, f"메시지 {i}")["id"] for i in range(2)]
    assert ids
    first = say(client, a, "점심은 부산 해운대 횟집에서 먹었어요")
    fake.data = {
        "questions": [
            q(
                source="chat",
                source_no=first["id"],
                evidence="부산 해운대",
                options=["부산 해운대", "강릉", "속초"],
                question="점심은 어디서 먹었을까?",
            )
        ]
    }
    body = get(client, a)
    assert body["state"] == "ok"
    assert body["items"][0]["source"] == "chat"
    assert "해운대" in fake.calls[0]["prompt"]


def test_questions_are_split_between_events_and_chat(client, ready, fake):
    a, b, _ = ready
    for text in ("다음 주에 부산 해운대에서 회 먹자", "좋아 해운대 가자", "점심은 횟집에서"):
        say(client, a, text)
    get(client, a)
    prompt = fake.calls[0]["prompt"]
    assert "일정에서 3개 안팎, 대화에서 4개 안팎(모두 7개 이하)" in prompt
    assert quiz_rec.ASK_COUNT == 7 and quiz_rec.SHOW_MAX == 7
    system = fake.calls[0]["system"]
    assert "한쪽 재료가 없거나" in system  # 모자라면 다른 쪽에서 채운다
    assert "억지로 채우지 말고" in system  # 쓸 사실이 적으면 적게 만들어도 된다
    assert "골고루 섞어" in system and "정답이 O 인 문제와 X 인 문제가 섞이게" in system
    assert "대화 자체를 묻는 문제는 만들지 않습니다" in system


def test_chat_only_asks_everything_from_chat(client, family, fake):
    a, b, _ = family
    enable_ai(client, a)
    for text in ("다음 주에 부산 해운대에서 회 먹자", "좋아 해운대 가자", "점심은 횟집에서"):
        say(client, a, text)
    fake.data = good()
    get(client, a)
    assert "대화에서 7개 이하" in fake.calls[0]["prompt"]


def test_no_material_means_no_call(client, family, fake):
    a, _, _ = family
    enable_ai(client, a)
    assert get(client, a) == {"state": "no_data", "items": []}
    assert fake.calls == []


def test_ai_off_state(client, family, fake):
    a, b, _ = family
    add_event(client, a, share_with=[me(client, b)])
    assert get(client, a) == {"state": "ai_off", "items": []}
    assert fake.calls == []


def test_failure_is_not_cached_and_retries_next_time(client, ready, fake):
    a, _, _ = ready
    fake.error = llm.LLMUnavailable("down")
    assert get(client, a) == {"state": "failed", "items": []}
    fake.error = None
    assert get(client, a)["state"] == "ok"  # 다음에 열면 다시 시도한다
    assert len(fake.calls) == 2


def test_zero_valid_questions_is_failure_and_not_cached(client, ready, fake):
    a, _, _ = ready
    fake.data = {"questions": [q(evidence="없는 근거")]}
    assert get(client, a)["state"] == "failed"
    with SessionLocal() as db:
        assert (
            db.scalar(select(AiResultCache).where(AiResultCache.feature == quiz_rec.FEATURE))
            is None
        )
    fake.data = good()
    assert get(client, a)["state"] == "ok"


def test_one_or_two_questions_still_count_as_success_and_cache(client, ready, fake):
    a, _, _ = ready
    assert get(client, a)["state"] == "ok"  # 문제 한 개
    get(client, a)
    assert len(fake.calls) == 1


def test_used_questions_are_hidden_at_read_time(client, ready, fake):
    a, b, _ = ready
    assert get(client, a)["state"] == "ok"
    made = client.post(
        "/play/quiz",
        json={
            "questions": [
                {
                    "qtype": 1,
                    "question": "여행지는 어디였을까?",
                    "options": ["O", "X"],
                    "answer_index": 0,
                }
            ]
        },
        headers=a,
    )
    assert made.status_code == 201, made.text
    assert get(client, b) == {"state": "used_up", "items": []}  # 캐시는 그대로, 낸 문제는 숨김
    assert len(fake.calls) == 1
    with SessionLocal() as db:
        assert (
            db.scalar(select(PlayQuiz).where(PlayQuiz.question == "여행지는 어디였을까?"))
            is not None
        )


def test_prompt_lists_recent_questions_to_avoid(client, ready, fake):
    a, _, _ = ready
    client.post(
        "/play/quiz",
        json={
            "questions": [
                {
                    "qtype": 2,
                    "question": "이전에 낸 문제예요",
                    "options": ["가", "나", "다"],
                    "answer_index": 0,
                }
            ]
        },
        headers=a,
    )
    get(client, a)
    assert "이전에 낸 문제예요" in fake.calls[0]["prompt"]


def test_cooldown_and_daily_limit_states(client, ready, fake):
    a, _, _ = ready
    fake.error = llm.LLMUnavailable("down")
    ai_guard.register_bucket(quiz_rec.FEATURE, ai_guard.Limits(60, 100, 100), (quiz_rec.FEATURE,))
    assert get(client, a)["state"] == "failed"
    assert get(client, a)["state"] == "cooldown"  # 방금 불렀다
    ai_guard.register_bucket(quiz_rec.FEATURE, ai_guard.Limits(0, 1, 1), (quiz_rec.FEATURE,))
    assert get(client, a) == {"state": "used_up", "items": []}  # 오늘 한도를 다 썼다


def test_other_family_does_not_share_the_cache(client, ready, other_family, fake):
    a, _, _ = ready
    assert get(client, a)["state"] == "ok"
    outsider, _ = other_family if isinstance(other_family, tuple) else (other_family, None)
    r = client.get(REC, headers=outsider)
    assert r.status_code == 200
    assert r.json()["state"] in ("no_data", "ai_off")


def test_requires_login(client):
    assert client.get(REC).status_code in (401, 403)


# ---------- 사용자마다 다르게 ----------
def four_questions():
    return {"questions": [q(question=f"여행지는 어디였을까 {k}?") for k in range(4)]}


def expected_ids(group, user_id, today=TODAY):
    everything = [{"id": quiz_rec._item_id(x["question"])} for x in four_questions()["questions"]]
    return [i["id"] for i in pick_for_user(everything, group["id"], user_id, today)]


@pytest.fixture
def app_day(monkeypatch):
    """서버가 보는 '오늘'을 정한 날짜(한국 시간 정오)로 고정한다. TODAY 는 시험 모듈을 불러온 날짜라, 전체 시험이 자정을 넘기면 서버의 오늘과 달라진다."""

    def set_day(day):
        noon = datetime.combine(day, time(12, 0), tzinfo=quiz_rec.local_tz())

        def now(cls, tz=None):
            return noon.astimezone(tz) if tz else noon.replace(tzinfo=None)

        monkeypatch.setattr(
            quiz_rec, "datetime", type("FrozenDatetime", (datetime,), {"now": classmethod(now)})
        )

    return set_day


def test_items_are_half_for_each_user(client, ready, fake, app_day):
    app_day(TODAY)  # 서버의 오늘을 고정해 자정을 넘겨 실행해도 같은 결과가 나온다(기대값은 그대로)
    a, b, group = ready
    fake.data = four_questions()
    for headers in (a, b):
        body = get(client, headers)
        assert body["state"] == "ok"
        assert [i["id"] for i in body["items"]] == expected_ids(group, me(client, headers))
        assert len(body["items"]) == 2


@pytest.mark.parametrize("days_later", [1, 2, 5])
def test_the_picked_half_follows_the_day_the_server_sees(client, ready, fake, app_day, days_later):
    """시험 모듈을 불러온 날과 서버의 오늘이 다를 때(자정을 넘긴 전체 실행)도 서버가 그날 기준으로 고른 절반을 돌려준다.
    예전 시험은 불러온 날짜로 기대값을 만들어 이때 가끔 실패했다."""
    day = TODAY + timedelta(days=days_later)
    app_day(day)
    a, b, group = ready
    fake.data = four_questions()
    for headers in (a, b):
        body = get(client, headers)
        assert body["state"] == "ok"
        assert [i["id"] for i in body["items"]] == expected_ids(group, me(client, headers), day)


def test_the_stale_import_day_really_gives_a_different_pick():
    """회귀 근거: 날짜가 바뀌면 고르는 절반이 실제로 달라질 수 있다(그래서 기대값의 날짜가 서버의 오늘과 같아야 한다)."""
    group = {"id": "g1"}
    fixed = date(2026, 11, 10)  # 실제 날짜와 무관하게 고정한 날짜로 본다
    picks = {tuple(expected_ids(group, "u1", fixed + timedelta(days=n))) for n in range(0, 8)}
    assert len(picks) > 1


def test_same_user_gets_same_items_on_reopen_and_ai_is_called_once(client, ready, fake):
    a, b, _ = ready
    fake.data = four_questions()
    first = get(client, a)
    assert get(client, a) == first
    get(client, b)
    assert len(fake.calls) == 1  # 가족 캐시는 전체 목록 그대로


def test_all_hidden_is_still_used_up(client, ready, fake):
    a, b, _ = ready
    assert get(client, a)["state"] == "ok"
    client.post(
        "/play/quiz",
        json={
            "questions": [
                {
                    "qtype": 1,
                    "question": "여행지는 어디였을까?",
                    "options": ["O", "X"],
                    "answer_index": 0,
                }
            ]
        },
        headers=a,
    )
    assert get(client, b) == {"state": "used_up", "items": []}
