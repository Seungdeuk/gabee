"""이게 뭐게 가비 추천 조립: 단어 뽑기, 그림 재사용·새로 그리기, 일부 실패, 하루 캐시, 상태. 실제 AI 는 부르지 않는다."""

import random
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.features.family_group.models import User
from app.features.play import draw_rec, draw_stock, draw_words
from app.features.play.constants import GAME_DRAW
from app.features.play.models import PlayDraw, PlayItem
from app.shared import ai_guard
from app.shared.ai_usage import AiUsageLog
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.errors import ApiError
from app.shared.llm import client as llm

NOW = datetime.now(UTC)
TODAY = NOW.astimezone(draw_rec.local_tz()).date()
DAY = TODAY + timedelta(days=3)
GOOD = {"strokes": [[[10, 10], [200, 10]], [[10, 20], [200, 20], [100, 100]], [[0, 0], [255, 255]]]}
BAD = {"strokes": [[[1, 1]]]}


class WordLLM:
    """프롬프트에 든 단어로 어떤 출력을 줄지 정하는 가짜 LLM. 정하지 않은 단어는 GOOD."""

    def __init__(self):
        self.calls = []
        self.by_word = {}
        self.error = None

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append(prompt)
        if self.error is not None:
            raise self.error
        data = next((d for w, d in self.by_word.items() if f"그릴 것: {w}" in prompt), GOOD)
        return llm.JsonResult(data=data, input_tokens=100, output_tokens=50, model="fake")


class Rng:
    """random() 값을 고정한 난수(재사용 확률 시험용)."""

    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value

    def choice(self, seq):
        return seq[0]


@pytest.fixture(autouse=True)
def loose_limits():
    ai_guard.register_bucket(draw_rec.FEATURE, ai_guard.Limits(0, 100, 100), (draw_rec.FEATURE,))
    yield
    draw_rec.register_limits()


@pytest.fixture
def fake(monkeypatch):
    f = WordLLM()
    monkeypatch.setattr(llm, "complete_json", f)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    return f


def me(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def enable_ai(client, headers):
    assert (
        client.put("/family-chat/ai/settings", json={"enabled": True}, headers=headers).status_code
        == 200
    )


def add_event(client, headers, **fields):
    body = {"title": "가족 모임", "start_date": DAY.isoformat(), **fields}
    r = client.post("/schedule/events", json=body, headers=headers)
    assert r.status_code == 201, r.text


def say(client, headers, text, room_id=None):
    body = {"text": text, **({"room_id": room_id} if room_id else {})}
    assert client.post("/family-chat/messages", json=body, headers=headers).status_code == 201


def only(monkeypatch, *picked):
    """뽑는 단어를 정해 둔다(단어 뽑기는 따로 시험한다)."""
    monkeypatch.setattr(draw_rec, "pick_words", lambda found, recent, rng: list(picked))


def user_of(db, client, headers):
    return db.get(User, me(client, headers))


@pytest.fixture
def ready(client, family):
    a, b, group = family
    enable_ai(client, a)
    return a, b, group


# ---------- 단어 뽑기 ----------
def test_family_words_from_events_and_chat(client, family):
    a, b, group = family
    add_event(client, a, memo="딸기 케이크 준비", share_with=[me(client, b)])
    add_event(client, a, title="혼자 일정", memo="수박")  # 공유하지 않은 내 일정은 빠진다
    say(client, a, "흑돼지 먹었다")
    direct = client.post(
        "/family-chat/rooms/direct", json={"user_id": me(client, b)}, headers=a
    ).json()
    say(client, a, "텐트 샀어", room_id=direct["id"])  # 1:1 방은 읽지 않는다
    with SessionLocal() as db:
        got = draw_rec.family_words(db, group["id"], TODAY, NOW)
    assert got == [("딸기", "schedule"), ("케이크", "schedule"), ("돼지", "chat")]


def test_pick_words_fills_with_common_words():
    rng = random.Random(1)
    picked = draw_rec.pick_words([("딸기", "schedule"), ("돼지", "chat")], {"사과"}, rng)
    assert len(picked) == draw_rec.ASK_COUNT
    assert picked[:2] == [("딸기", "schedule"), ("돼지", "chat")]
    words = [w for w, _ in picked]
    assert len(set(words)) == 5 and "사과" not in words
    assert [s for _, s in picked[2:]] == ["common"] * 3


def test_pick_words_with_no_material_is_all_common():
    picked = draw_rec.pick_words([], set(), random.Random(2))
    assert len(picked) == draw_rec.ASK_COUNT
    assert {s for _, s in picked} == {"common"}


def test_pick_words_skips_recent_and_alt_answers():
    # 최근에 "케익"으로 낸 가족은 케이크도 안 나온다
    picked = draw_rec.pick_words(
        [("케이크", "schedule"), ("딸기", "schedule")], {"케익"}, random.Random(3)
    )
    assert "케이크" not in [w for w, _ in picked]
    assert ("딸기", "schedule") in picked


def test_pick_words_gives_what_it_can_when_pool_is_short(monkeypatch):
    few = {w: draw_words.DrawWord(w, ()) for w in ("딸기", "텐트", "바다")}
    monkeypatch.setattr(draw_words, "load_words", lambda: few)
    picked = draw_rec.pick_words([("딸기", "schedule")], {"텐트"}, random.Random(4))
    assert sorted(w for w, _ in picked) == ["딸기", "바다"]  # 5개를 억지로 채우지 않고 중복도 없다


def test_pick_words_samples_when_material_has_more_than_five():
    found = [(w, "schedule") for w in ("딸기", "텐트", "바다", "케이크", "선물", "돼지", "사과")]
    picked = draw_rec.pick_words(found, set(), random.Random(5))
    assert len(picked) == 5 and set(picked) <= set(found)


def test_pick_words_keeps_the_rest_when_one_word_becomes_recent():
    # 같은 날 같은 가족이 그림 하나를 내면 그 단어만 바뀌고 나머지 4개는 그대로여야 한다(다시 불러올 때 단어가 통째로 바뀌지 않게)
    first = draw_rec.pick_words([], set(), random.Random(7))
    gone = first[0][0]
    again = draw_rec.pick_words([], {gone}, random.Random(7))
    assert gone not in {w for w, _ in again}
    assert len({w for w, _ in first} & {w for w, _ in again}) == 4


def test_pick_words_keeps_the_rest_when_material_has_more_than_five():
    found = [(w, "schedule") for w in ("딸기", "텐트", "바다", "케이크", "선물", "돼지", "사과")]
    first = draw_rec.pick_words(found, set(), random.Random(8))
    gone = first[0][0]
    again = draw_rec.pick_words(found, {gone}, random.Random(8))
    assert len(set(first) & set(again)) == 4 and gone not in {w for w, _ in again}


def test_daily_rng_is_stable_per_family_and_day():
    a1 = [draw_rec.daily_rng("g1", TODAY).random() for _ in range(3)]
    a2 = [draw_rec.daily_rng("g1", TODAY).random() for _ in range(3)]
    b = [draw_rec.daily_rng("g2", TODAY).random() for _ in range(3)]
    assert a1 == a2 and a1 != b


def test_recent_words_are_this_familys_answers_and_alts_in_30_days(client, ready):
    a, _, group = ready
    with SessionLocal() as db:
        maker = me(client, a)
        for days, answer, alts in ((3, "케이크", ["케익"]), (40, "텐트", [])):
            item = PlayItem(
                group_id=group["id"],
                game=GAME_DRAW,
                maker_id=maker,
                close_at=NOW,
                created_at=NOW - timedelta(days=days),
            )
            db.add(item)
            db.flush()
            db.add(PlayDraw(play_id=item.id, image_path="x.png", answer=answer, alt_answers=alts))
        db.commit()
        assert draw_rec.recent_words(db, group["id"], NOW) == {"케이크", "케익"}


# ---------- 추천 ----------
def test_recommend_reuses_stock_without_calling_ai(client, ready, fake, monkeypatch):
    a, _, group = ready
    only(monkeypatch, ("케이크", "schedule"))
    with SessionLocal() as db:
        stored = draw_stock.add_variant(db, "케이크", GOOD["strokes"], NOW - timedelta(days=2))
        out = draw_rec._recommend_family(db, user_of(db, client, a), group["id"], rng=Rng(0.5))
        assert out["state"] == "ok"
        assert [i["id"] for i in out["items"]] == [stored.id]
    assert fake.calls == []


def test_recommend_redraws_by_rate_and_adds_variant(client, ready, fake, monkeypatch):
    a, _, group = ready
    only(monkeypatch, ("케이크", "schedule"))
    with SessionLocal() as db:
        stored = draw_stock.add_variant(db, "케이크", GOOD["strokes"], NOW - timedelta(days=2))
        out = draw_rec._recommend_family(db, user_of(db, client, a), group["id"], rng=Rng(0.1))
        assert len(fake.calls) == 1
        assert out["items"][0]["id"] != stored.id
        assert len(draw_stock.stock_variants(db, "케이크", NOW)) == 2


def test_recommend_always_draws_when_nothing_stored(client, ready, fake, monkeypatch):
    a, _, group = ready
    only(monkeypatch, ("케이크", "schedule"), ("딸기", "chat"))
    with SessionLocal() as db:
        out = draw_rec._recommend_family(db, user_of(db, client, a), group["id"], rng=Rng(0.99))
        assert [(i["word"], i["source"]) for i in out["items"]] == [
            ("케이크", "schedule"),
            ("딸기", "chat"),
        ]
        assert len(fake.calls) == 2


def test_recommend_item_shape_and_no_family_text_to_ai(client, ready, fake, monkeypatch):
    a, b, group = ready
    add_event(
        client, a, title="민수 생일파티", place="우리집", memo="케이크", share_with=[me(client, b)]
    )
    only(monkeypatch, ("케이크", "schedule"))
    with SessionLocal() as db:
        out = draw_rec._recommend_family(db, user_of(db, client, a), group["id"], rng=Rng(0.5))
    item = out["items"][0]
    assert set(item) == {"id", "source", "word", "alt_answers", "strokes"}
    assert item["alt_answers"] == ["케익", "케잌"] and item["strokes"] == GOOD["strokes"]
    joined = " ".join(fake.calls)
    assert (
        "케이크" in joined
        and "민수" not in joined
        and "생일파티" not in joined
        and "우리집" not in joined
    )


def test_partial_shows_made_and_fills_in_on_retry(client, ready, fake, monkeypatch):
    a, _, group = ready
    only(monkeypatch, ("케이크", "schedule"), ("딸기", "common"), ("텐트", "common"))
    fake.by_word = {"딸기": BAD, "텐트": BAD}
    with SessionLocal() as db:
        user = user_of(db, client, a)
        first = draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99))
        assert first["state"] == "partial" and [i["word"] for i in first["items"]] == ["케이크"]
        fake.by_word = {}  # 다시 시도하면 모자란 단어를 채운다(만든 그림은 그대로)
        used = len(fake.calls)
        second = draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99))
        assert len(fake.calls) > used
        assert second["state"] == "ok" and [i["word"] for i in second["items"]] == [
            "케이크",
            "딸기",
            "텐트",
        ]
        assert second["items"][0]["id"] == first["items"][0]["id"]
        used = len(fake.calls)
        assert (
            draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99)) == second
        )  # 다 모이면 오늘은 캐시
        assert len(fake.calls) == used


def test_retry_keeps_pictures_drawn_today_even_when_redraw_roll_says_redraw(
    client, ready, fake, monkeypatch
):
    a, _, group = ready
    five = [(w, "common") for w in ("케이크", "딸기", "텐트", "사과", "우산")]
    only(monkeypatch, *five)
    fake.by_word = {"우산": BAD}
    with SessionLocal() as db:
        user = user_of(db, client, a)
        first = draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99))
        assert first["state"] == "partial" and len(first["items"]) == 4
        fake.by_word = {}
        used = len(fake.calls)
        second = draw_rec._recommend_family(
            db, user, group["id"], rng=Rng(0.0)
        )  # 0.0 은 "새로 그리기" 쪽 값
        new_prompts = fake.calls[used:]
        assert second["state"] == "ok" and len(second["items"]) == 5
        assert new_prompts and all(
            "그릴 것: 우산" in p for p in new_prompts
        )  # 모자란 한 단어만 새로 그린다
        assert [i["id"] for i in second["items"][:4]] == [
            i["id"] for i in first["items"]
        ]  # 오늘 그린 4개는 그대로


def test_ok_shows_the_same_picture_the_partial_showed(client, ready, fake, monkeypatch):
    a, _, group = ready
    only(monkeypatch, ("케이크", "common"), ("우산", "common"))
    fake.by_word = {"우산": BAD}
    now = datetime.now(UTC)
    for days in (3, 2):  # 어제 이전에 쌓인 케이크 그림 둘(오늘 그린 것은 없다)
        with SessionLocal() as seed:
            draw_stock.add_variant(seed, "케이크", GOOD["strokes"], now - timedelta(days=days))
    with (
        SessionLocal() as db
    ):  # 요청마다 세션이 따로다(같은 세션을 이어 쓰면 SQLite 에서 시간대 비교 오류가 날 수 있다)
        first = draw_rec._recommend_family(db, user_of(db, client, a), group["id"], rng=Rng(0.99))
    assert first["state"] == "partial" and [i["word"] for i in first["items"]] == ["케이크"]
    fake.by_word = {}
    with SessionLocal() as db:
        second = draw_rec._recommend_family(db, user_of(db, client, a), group["id"], rng=Rng(0.99))
    assert second["state"] == "ok"
    assert (
        second["items"][0]["id"] == first["items"][0]["id"]
    )  # 5개가 다 모여도 보던 그림이 바뀌지 않는다


def test_attempts_are_three_then_made_ones_stay_visible(client, ready, fake, monkeypatch):
    a, _, group = ready
    ai_guard.register_bucket(draw_rec.FEATURE, ai_guard.Limits(0, 3, 5), (draw_rec.FEATURE,))
    only(monkeypatch, ("케이크", "schedule"), ("딸기", "common"))
    fake.by_word = {"딸기": BAD}
    with SessionLocal() as db:
        user = user_of(db, client, a)
        states = [
            draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99))["state"]
            for _ in range(3)
        ]
        assert states == ["partial"] * 3  # 시도 3번(그때마다 1번으로 센다)
        calls = len(fake.calls)
        last = draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99))
        assert len(fake.calls) == calls  # 더 부르지 않는다
        assert last["state"] == "ok" and [i["word"] for i in last["items"]] == [
            "케이크"
        ]  # 만든 그림은 계속 보인다


def test_three_attempts_with_nothing_drawn_is_used_up_without_items(
    client, ready, fake, monkeypatch
):
    a, _, group = ready
    ai_guard.register_bucket(draw_rec.FEATURE, ai_guard.Limits(0, 3, 5), (draw_rec.FEATURE,))
    only(monkeypatch, ("케이크", "schedule"), ("딸기", "common"))
    fake.by_word = {"케이크": BAD, "딸기": BAD}
    with SessionLocal() as db:
        user = user_of(db, client, a)
        states = [
            draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99))["state"]
            for _ in range(3)
        ]
        assert states == ["failed"] * 3
        assert draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99)) == {
            "state": "used_up",
            "items": [],
        }


def test_all_failed_is_failure_and_not_cached(client, ready, fake, monkeypatch):
    a, _, group = ready
    only(monkeypatch, ("케이크", "schedule"), ("딸기", "common"))
    fake.by_word = {"케이크": BAD, "딸기": BAD}
    with SessionLocal() as db:
        user = user_of(db, client, a)
        assert draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99)) == {
            "state": "failed",
            "items": [],
        }
        before = len(fake.calls)
        draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99))
        assert len(fake.calls) > before  # 캐시되지 않아 다음에 다시 시도한다


def test_llm_down_is_failure(client, ready, fake, monkeypatch):
    a, _, group = ready
    only(monkeypatch, ("케이크", "schedule"))
    fake.error = llm.LLMUnavailable("down")
    with SessionLocal() as db:
        out = draw_rec._recommend_family(db, user_of(db, client, a), group["id"], rng=Rng(0.99))
    assert out == {"state": "failed", "items": []}


def test_recent_words_are_hidden_from_cached_items(client, ready, fake, monkeypatch):
    a, _, group = ready
    only(monkeypatch, ("케이크", "schedule"), ("딸기", "common"))
    with SessionLocal() as db:
        user = user_of(db, client, a)
        draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99))
        item = PlayItem(
            group_id=group["id"], game=GAME_DRAW, maker_id=user.id, close_at=NOW, created_at=NOW
        )
        db.add(item)
        db.flush()
        db.add(PlayDraw(play_id=item.id, image_path="x.png", answer="케이크", alt_answers=None))
        db.commit()
        out = draw_rec._recommend_family(
            db, user, group["id"], rng=Rng(0.99)
        )  # 캐시된 묶음에서 낸 단어는 숨긴다
        assert [i["word"] for i in out["items"]] == ["딸기"]


def test_prompts_sent_to_ai_hold_only_the_word_never_family_text(client, ready, fake):
    """가족 일정·대화에서 단어를 찾아도 AI 로 가는 요청은 단어 하나짜리 고정 프롬프트뿐이다(일정 제목·메모·대화 원문은 나가지 않는다)."""
    a, b, group = ready
    add_event(
        client,
        a,
        title="딸기 파티 보안메모ZZ",
        memo="비밀장소QQ 케이크",
        share_with=[me(client, b)],
    )
    say(client, a, "흑돼지 먹으러 갈까 대화원문XX")
    with SessionLocal() as db:
        out = draw_rec._recommend_family(db, user_of(db, client, a), group["id"])
    words = {i["word"] for i in out["items"]}
    assert {
        "딸기",
        "케이크",
        "돼지",
    } <= words  # 가족 재료를 실제로 읽었다(아래 검사가 빈 검사가 아니다)
    assert fake.calls
    allowed = {draw_rec.draw_prompt(w) for w in words}
    for prompt in fake.calls:
        assert prompt in allowed
        assert not any(s in prompt for s in ("보안메모ZZ", "비밀장소QQ", "대화원문XX"))


def test_ai_off_state(client, family, fake):
    a, _, group = family
    with SessionLocal() as db:
        out = draw_rec._recommend_family(db, user_of(db, client, a), group["id"])
    assert out == {"state": "ai_off", "items": []}
    assert fake.calls == []


@pytest.mark.parametrize(
    ("code", "state"),
    [
        ("ai_busy", "preparing"),
        ("ai_cooldown", "cooldown"),
        ("ai_daily_limit_user", "used_up"),
        ("llm_failed", "failed"),
    ],
)
def test_guard_errors_become_states(client, ready, fake, monkeypatch, code, state):
    a, _, group = ready

    def boom(*args, **kwargs):
        raise ApiError(429, code, "x")

    monkeypatch.setattr(draw_rec.ai_guard, "run", boom)
    with SessionLocal() as db:
        assert draw_rec._recommend_family(db, user_of(db, client, a), group["id"]) == {
            "state": state,
            "items": [],
        }


def test_limits_are_registered_with_settings():
    # 골든벨과 같다: 사용자 하루 3회, 가족 하루 5회(추천 한 번이 1회, 성공하면 캐시라 2·3회는 실패했을 때의 시도분)
    assert settings.ai_play_draw_rec_cooldown_seconds == 5
    assert settings.ai_play_draw_rec_max_calls_per_user_per_day == 3
    assert settings.ai_play_draw_rec_max_calls_per_group_per_day == 5


def test_one_recommendation_counts_as_one_attempt(client, ready, fake, monkeypatch):
    a, _, group = ready
    only(monkeypatch, ("케이크", "schedule"), ("딸기", "common"), ("텐트", "common"))
    with SessionLocal() as db:
        draw_rec._recommend_family(db, user_of(db, client, a), group["id"], rng=Rng(0.99))
        assert len(fake.calls) == 3  # 그림 3개를 불렀어도
        logged = db.scalar(
            select(func.coalesce(func.sum(AiUsageLog.api_calls), 0)).where(
                AiUsageLog.feature == draw_rec.FEATURE
            )
        )
        out_tokens = db.scalar(
            select(func.coalesce(func.sum(AiUsageLog.output_tokens), 0)).where(
                AiUsageLog.feature == draw_rec.FEATURE
            )
        )
    assert logged == 1  # 한도에는 시도 1회
    assert out_tokens == 150  # 비용(토큰)은 실제 호출 3번분


def test_failed_attempts_use_up_the_three_tries(client, ready, fake, monkeypatch):
    a, _, group = ready
    ai_guard.register_bucket(draw_rec.FEATURE, ai_guard.Limits(0, 3, 100), (draw_rec.FEATURE,))
    only(monkeypatch, ("케이크", "schedule"))
    fake.error = llm.LLMUnavailable("down")
    with SessionLocal() as db:
        user = user_of(db, client, a)
        for _ in range(3):  # 실패는 캐시하지 않아 다시 시도하고 그때마다 1회로 센다
            assert (
                draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99))["state"]
                == "failed"
            )
        assert len(fake.calls) == 3
        assert draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99)) == {
            "state": "used_up",
            "items": [],
        }
        assert len(fake.calls) == 3  # 한도가 차면 AI 를 부르지 않는다


def test_success_ends_it_and_later_opens_do_not_count(client, ready, fake, monkeypatch):
    a, _, group = ready
    ai_guard.register_bucket(draw_rec.FEATURE, ai_guard.Limits(0, 3, 100), (draw_rec.FEATURE,))
    only(monkeypatch, ("케이크", "schedule"))
    with SessionLocal() as db:
        user = user_of(db, client, a)
        first = draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99))
        for _ in range(5):  # 오늘은 캐시라 몇 번을 열어도 AI 도 한도도 쓰지 않는다
            assert draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99)) == first
        assert len(fake.calls) == 1


def test_partial_is_also_picked_per_user(client, ready, fake, monkeypatch):
    a, _, group = ready
    only(
        monkeypatch,
        ("케이크", "schedule"),
        ("딸기", "common"),
        ("텐트", "common"),
        ("수박", "common"),
    )
    fake.by_word = {"수박": BAD}
    with SessionLocal() as db:
        user = user_of(db, client, a)
        whole = draw_rec._recommend_family(db, user, group["id"], rng=Rng(0.99))
        assert whole["state"] == "partial" and len(whole["items"]) == 3
        out = draw_rec.recommend(db, user, group["id"], rng=Rng(0.99))
        assert out["state"] == "partial" and len(out["items"]) == 2  # 3개 중 절반 올림
        assert {i["id"] for i in out["items"]} <= {i["id"] for i in whole["items"]}
