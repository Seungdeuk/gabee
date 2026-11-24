"""주간 가족 뉴스 생성(`POST /report/news`) 시험. LLM 은 가짜로 바꾸고 외부 네트워크는 부르지 않는다(부르면 실패).

재료 제공자는 시험이 `weekly_sources._providers` 를 바꿔 끼운다(실제 일정·문서 DB 대신). 시간은 `current_time` 으로 고정한다.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.features.weekly_news import generate
from app.features.weekly_news import router as news_router
from app.features.weekly_news.models import MemberWeeklyNews
from app.main import app
from app.shared import ai_guard, weekly_sources
from app.shared.ai_usage import AiUsageLog
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from app.shared.weekly_sources import SourceRecord

URL = "/report/news"
LAST_MON = date(2026, 11, 2)
WED = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)  # 수요일 12:00 KST
SUN_1759 = datetime(2026, 11, 15, 8, 59, tzinfo=UTC)
THIS_MON = date(2026, 11, 9)


class FakeLLM:
    """llm.complete_json 대신 쓰는 가짜. 호출 수와 프롬프트를 센다."""

    def __init__(self):
        self.calls = []
        self.data = None
        self.error = None

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append({"prompt": prompt, "schema": schema, "system": system, **kw})
        if self.error is not None:
            raise self.error
        data = self.data if self.data is not None else good()
        return llm.JsonResult(data=data, input_tokens=120, output_tokens=40, model="fake-model")


def good():
    return {
        "title": "공연과 생일이 있던 주",
        "items": [
            {"text": "화요일 오후 2시 30분에 학교 공연이 있었어요", "source_ids": ["e1"]},
            {"text": "[PERSON_1] 생일 파티가 있었어요", "source_ids": ["e2"]},
        ],
    }


RECORDS = [
    SourceRecord("event", "ev-1", "학교 공연", date(2026, 11, 3), "14:30"),
    SourceRecord("event", "ev-2", "지민 생일 파티", date(2026, 11, 7), "18:00"),
]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ai_day_utc_offset_hours", 9)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_request_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "ai_news_cooldown_seconds", 0)
    generate.register()

    def no_http(*a, **k):
        raise AssertionError("httpx 가 불렸다")

    monkeypatch.setattr(httpx, "post", no_http)
    monkeypatch.setattr(httpx.Client, "post", no_http)
    monkeypatch.setattr(httpx.Client, "send", no_http)
    yield
    monkeypatch.undo()
    generate.register()


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(llm, "complete_json", f)
    return f


@pytest.fixture
def at():
    def set_now(now: datetime) -> None:
        app.dependency_overrides[news_router.current_time] = lambda: now

    set_now(WED)
    yield set_now
    app.dependency_overrides.pop(news_router.current_time, None)


@pytest.fixture
def records(monkeypatch):
    """재료 제공자를 가짜로 바꾼다. `records.items` 를 바꾸면 다음 수집부터 반영된다."""

    class Box:
        items = list(RECORDS)
        fail = False
        reads = 0

    def provider(db, group_id, user_id, start, end):
        Box.reads += 1
        if Box.fail:
            raise RuntimeError("provider down")
        return list(Box.items)

    monkeypatch.setitem(weekly_sources._providers, "schedule", ("schedule", provider))
    # 주인 기능 이름은 준비된 기능(schedule)으로: 모르는 이름이면 monitor 가 "준비 안 됨" 으로 보고 unavailable 이 된다
    monkeypatch.setitem(weekly_sources._providers, "documents", ("schedule", lambda *a: []))
    return Box


def _ids(client, headers) -> tuple[str, str]:
    me = client.get("/family-group/me", headers=headers).json()
    return me["id"], me["active_group_id"]


def _enable(group_id: str, user_id: str, value: bool = True) -> None:
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group_id, user_id, value)


@pytest.fixture
def ready(client, family, fake, at, records):
    a, b, _ = family
    uid, gid = _ids(client, a)
    _enable(gid, uid)
    return a, b


def post(client, headers, week=LAST_MON):
    return client.post(URL, params={"week_start": week.isoformat()}, headers=headers)


def rows(**where):
    with SessionLocal() as db:
        q = select(MemberWeeklyNews)
        for k, v in where.items():
            q = q.where(getattr(MemberWeeklyNews, k) == v)
        return list(db.scalars(q))


def logs():
    with SessionLocal() as db:
        return list(db.scalars(select(AiUsageLog).where(AiUsageLog.feature == generate.FEATURE)))


# ── 정상 흐름 ─────────────────────────────────────────────────


def test_generates_validates_restores_names_and_saves(client, ready, fake):
    a, _ = ready
    r = post(client, a)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready" and body["ai_generated"] is True
    assert body["title"] == "공연과 생일이 있던 주"
    texts = [i["text"] for i in body["items"]]
    assert "지민 생일 파티가 있었어요" in texts  # 토큰이 실제 이름으로 되돌아왔다
    assert not any("[PERSON" in t for t in texts)
    assert {s["id"] for s in body["sources"]} == {"e1", "e2"}
    assert body["model"] == "fake-model"
    assert len(fake.calls) == 1
    saved = rows()
    assert len(saved) == 1 and saved[0].status == "ok" and saved[0].prompt_version == "v3"
    assert saved[0].input_tokens == 120 and saved[0].output_tokens == 40
    assert [lg.status for lg in logs()] == ["ok"]


def test_real_names_never_reach_the_llm_prompt(client, ready, fake):
    a, _ = ready
    assert post(client, a).status_code == 200
    sent = fake.calls[0]["prompt"] + (fake.calls[0]["system"] or "")
    assert "지민" not in sent and "수진" not in sent
    assert "[PERSON_1]" in sent
    assert "학교 공연" in sent  # 이름이 아닌 제목은 그대로
    # 메모·장소·본문 같은 필드는 프롬프트에 없다: 기록은 id·종류·날짜·요일(서버가 날짜에서 계산)·시각·제목만
    assert set(__import__("json").loads(fake.calls[0]["prompt"].split("기록:\n")[1])[0]) == {
        "id",
        "kind",
        "date",
        "weekday",
        "time",
        "title",
    }


def test_second_call_returns_saved_news_without_calling_the_llm(client, ready, fake):
    a, _ = ready
    first = post(client, a).json()
    second = post(client, a).json()
    assert len(fake.calls) == 1
    assert second == first
    assert len(rows()) == 1 and len(logs()) == 1


def test_get_returns_what_post_saved(client, ready):
    a, _ = ready
    made = post(client, a).json()
    got = client.get(URL, params={"week_start": LAST_MON.isoformat()}, headers=a).json()
    assert got == made


def test_each_member_gets_their_own_news(client, ready, fake):
    a, b = ready
    assert post(client, a).status_code == 200
    assert post(client, b).status_code == 200
    assert len(fake.calls) == 2
    assert len(rows()) == 2


def test_model_setting_is_passed_when_set(client, ready, fake, monkeypatch):
    a, _ = ready
    monkeypatch.setattr(settings, "weekly_news_model", "claude-test-model")
    post(client, a)
    assert fake.calls[0]["model"] == "claude-test-model"


# ── 막히는 경우 ───────────────────────────────────────────────


def test_ai_not_enabled_is_403_and_leaves_nothing(client, family, fake, at, records):
    a, _, _ = family
    r = post(client, a)
    assert r.status_code == 403 and r.json()["code"] == "ai_not_enabled"
    assert fake.calls == [] and rows() == [] and logs() == []


def test_this_week_before_sunday_1800_is_409(client, ready, fake, at):
    a, _ = ready
    at(SUN_1759)
    r = post(client, a, week=THIS_MON)
    assert r.status_code == 409 and r.json()["code"] == "news_not_ready"
    assert fake.calls == [] and rows() == []


@pytest.mark.parametrize("week", [date(2026, 11, 3), date(2026, 11, 16), date(2025, 1, 6)])
def test_invalid_week_is_400(client, ready, week):
    a, _ = ready
    r = post(client, a, week=week)
    assert r.status_code == 400 and r.json()["code"] == "invalid_week"


def test_no_materials_is_empty_without_calling_the_llm(client, ready, fake, records):
    a, _ = ready
    records.items = []
    r = post(client, a)
    assert r.status_code == 200 and r.json()["status"] == "empty"
    assert fake.calls == [] and [x.status for x in rows()] == ["empty"]
    assert logs() == []


def test_empty_week_can_be_generated_later_when_materials_appear(client, ready, fake, records):
    a, _ = ready
    records.items = []
    assert post(client, a).json()["status"] == "empty"
    records.items = list(RECORDS)
    assert post(client, a).json()["status"] == "ready"
    assert len(fake.calls) == 1 and [x.status for x in rows()] == ["ok"]


def test_all_providers_failing_is_failed_and_retryable_not_empty(client, ready, fake, records):
    a, _ = ready
    records.fail = True
    r = post(client, a)
    assert r.status_code == 200 and r.json()["status"] == "failed"
    assert fake.calls == []
    assert rows()[0].error_code == "sources_unavailable"
    records.fail = False  # 제공자가 돌아오면 다시 만들 수 있다
    assert post(client, a).json()["status"] == "ready"


# ── 실패·검증 ─────────────────────────────────────────────────


def test_llm_failure_is_failed_status_and_can_be_retried(client, ready, fake):
    a, _ = ready
    fake.error = llm.LLMUnavailable("down")
    r = post(client, a)
    assert r.status_code == 200 and r.json()["status"] == "failed"
    assert r.json()["items"] == []
    row = rows()[0]
    assert row.status == "failed" and row.error_code == "llm_failed" and row.body is None
    fake.error = None
    again = post(client, a).json()
    assert again["status"] == "ready" and len(fake.calls) == 2
    assert [x.status for x in rows()] == ["ok"]


def test_hallucinated_sentences_are_dropped_and_good_ones_kept(client, ready, fake):
    a, _ = ready
    fake.data = {
        "title": "한 주",
        "items": [
            {"text": "화요일 오후 2시 30분에 학교 공연이 있었어요", "source_ids": ["e1"]},
            {"text": "없는 기록을 인용한 문장이에요", "source_ids": ["e9"]},
            {"text": "학교 공연에 99명이 모였어요", "source_ids": ["e1"]},
            {"text": "근거를 안 댄 문장이에요", "source_ids": []},
        ],
    }
    body = post(client, a).json()
    assert body["status"] == "ready"
    assert [i["source_ids"] for i in body["items"]] == [["e1"]]
    assert [s["id"] for s in body["sources"]] == ["e1"]


def test_unknown_pseudonym_token_sentence_is_dropped(client, ready, fake):
    a, _ = ready
    fake.data = {
        "title": "한 주",
        "items": [
            {"text": "[PERSON_2] 생일 파티가 있었어요", "source_ids": ["e2"]},
            {"text": "화요일 오후 2시 30분에 학교 공연이 있었어요", "source_ids": ["e1"]},
        ],
    }
    body = post(client, a).json()
    assert [i["source_ids"] for i in body["items"]] == [["e1"]]
    assert "PERSON" not in str(body)


def test_token_not_in_the_cited_source_is_dropped(client, ready, fake):
    # [PERSON_1] 은 e2 의 제목에만 있다. e1 을 인용하면서 그 사람 이름을 쓰면 버린다
    a, _ = ready
    fake.data = {
        "title": "한 주",
        "items": [
            {"text": "[PERSON_1] 와 학교 공연에 갔어요", "source_ids": ["e1"]},
            {"text": "화요일 오후 2시 30분에 학교 공연이 있었어요", "source_ids": ["e1"]},
        ],
    }
    body = post(client, a).json()
    assert len(body["items"]) == 1 and "지민" not in str(body)


def test_no_valid_sentence_is_failed_with_invalid_output(client, ready, fake):
    a, _ = ready
    fake.data = {"title": "x", "items": [{"text": "근거 없음", "source_ids": ["e9"]}]}
    r = post(client, a)
    assert r.status_code == 200 and r.json()["status"] == "failed"
    row = rows()[0]
    assert row.status == "failed" and row.error_code == "invalid_output"
    assert row.model == "fake-model" and row.input_tokens == 120


def test_bad_shape_is_failed(client, ready, fake):
    a, _ = ready
    fake.data = {"title": "x", "items": "문자열"}
    assert post(client, a).json()["status"] == "failed"
    fake.data = {"unexpected": 1}
    assert post(client, a).json()["status"] == "failed"


# ── 한도·동시성 ────────────────────────────────────────────────


def test_per_user_daily_limit_is_429_and_leaves_no_pending_row(client, ready, fake, monkeypatch):
    a, _ = ready
    monkeypatch.setattr(settings, "ai_news_max_calls_per_user_per_day", 1)
    generate.register()
    fake.error = llm.LLMUnavailable("down")
    assert post(client, a).json()["status"] == "failed"  # 1회 사용
    fake.error = None
    r = post(client, a)
    assert r.status_code == 429, r.text
    assert [x.status for x in rows()] == ["failed"]  # pending 이 아니라 직전 실패 줄이 남는다
    assert len(fake.calls) == 1


def test_limit_exceeded_on_first_try_leaves_no_row(client, ready, fake, monkeypatch):
    a, _ = ready
    monkeypatch.setattr(settings, "ai_news_max_calls_per_user_per_day", 0)
    generate.register()
    r = post(client, a)
    assert r.status_code == 429
    assert rows() == [] and fake.calls == []


def test_missing_api_key_is_503_and_leaves_no_row(client, ready, fake, monkeypatch):
    a, _ = ready
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    # complete_json 은 가짜지만 llm.available() 이 키를 본다
    r = post(client, a)
    assert r.status_code == 503 and r.json()["code"] == "llm_unavailable"
    assert rows() == [] and fake.calls == []


def _put_pending(user_id, group_id, updated_at):
    with SessionLocal() as db:
        db.add(
            MemberWeeklyNews(
                id=uuid.uuid4().hex,
                group_id=group_id,
                user_id=user_id,
                week_start=LAST_MON,
                status="pending",
                created_at=updated_at,
                updated_at=updated_at,
            )
        )
        db.commit()


def test_fresh_pending_row_blocks_a_second_generation(client, ready, fake):
    a, _ = ready
    uid, gid = _ids(client, a)
    _put_pending(uid, gid, WED - timedelta(seconds=30))  # 시험의 현재(WED) 기준으로 방금
    r = post(client, a)
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert fake.calls == []


def test_stale_pending_row_is_taken_over(client, ready, fake, at):
    a, _ = ready
    uid, gid = _ids(client, a)
    _put_pending(uid, gid, WED - timedelta(minutes=30))
    r = post(client, a)
    assert r.json()["status"] == "ready" and len(fake.calls) == 1
    assert [x.status for x in rows()] == ["ok"]


def test_claim_is_exclusive_when_two_requests_race(client, ready):
    from app.features.weekly_news import repository

    a, _ = ready
    uid, gid = _ids(client, a)
    with SessionLocal() as db1, SessionLocal() as db2:
        first = repository.claim(db1, gid, uid, LAST_MON, WED, generate.PENDING_STALE)
        second = repository.claim(db2, gid, uid, LAST_MON, WED, generate.PENDING_STALE)
    assert first is not None and second is None
    assert [x.status for x in rows()] == ["pending"]


def test_failed_row_is_claimable_again_but_ok_row_is_not(client, ready):
    from app.features.weekly_news import repository

    a, _ = ready
    uid, gid = _ids(client, a)
    with SessionLocal() as db:
        repository.save_status(db, gid, uid, LAST_MON, "failed", "llm_failed", WED)
        assert repository.claim(db, gid, uid, LAST_MON, WED, generate.PENDING_STALE) is not None
        repository.save_ok(
            db,
            gid,
            uid,
            LAST_MON,
            body={"title": "t", "items": []},
            sources=[],
            model="m",
            prompt_version="v1",
            input_tokens=1,
            output_tokens=1,
            now=WED,
        )
        assert repository.claim(db, gid, uid, LAST_MON, WED, generate.PENDING_STALE) is None


# ── 권한 ──────────────────────────────────────────────────────


def test_other_family_cannot_see_or_trigger_my_news(client, ready, other_family, fake):
    a, _ = ready
    post(client, a)
    r = client.get(URL, params={"week_start": LAST_MON.isoformat()}, headers=other_family)
    assert r.json()["status"] in ("not_generated", "too_early")
    outsider = post(client, other_family)  # 그 가족은 AI 동의가 꺼져 있다
    assert outsider.status_code == 403
    assert len(fake.calls) == 1


def test_post_requires_login(client):
    r = client.post(URL)
    assert r.status_code in (401, 403)


def test_usage_log_has_no_news_text(client, ready):
    a, _ = ready
    post(client, a)
    for lg in logs():
        dumped = str({c.name: getattr(lg, c.name) for c in lg.__table__.columns})
        assert "학교 공연" not in dumped and "생일" not in dumped


def test_saved_news_is_returned_without_reading_materials_again(client, ready, records):
    a, _ = ready
    post(client, a)
    reads = records.reads
    post(client, a)
    assert records.reads == reads  # 저장된 ok 뉴스는 재료를 다시 모으지도 않는다


def test_ai_off_with_no_materials_does_not_write_an_empty_row(client, family, fake, at, records):
    a, _, _ = family
    records.items = []
    r = post(client, a)
    assert r.status_code == 403 and rows() == []


def test_restored_names_are_validated_again_against_the_real_sources(client, ready, fake, records):
    """가명 상태(토큰 10자)에서는 120자 안인데 실제 이름으로 되돌리면 넘는 문장은 버린다(복원 뒤 재검증)."""
    from app.features.family_group.models import User

    a, _ = ready
    uid, _ = _ids(client, a)
    long_name = "가나다라마바사아자차카타파하거너더러"  # 18자
    with SessionLocal() as db:
        db.get(User, uid).name = long_name
        db.commit()
    records.items = [SourceRecord("event", "ev-9", f"{long_name} 생일", date(2026, 11, 7), None)]
    text = " ".join(["[PERSON_1]"] * 9)  # 89자 → 되돌리면 9*18+8 = 170자
    fake.data = {"title": "x", "items": [{"text": text, "source_ids": ["e1"]}]}
    r = post(client, a)
    assert r.json()["status"] == "failed"
    assert rows()[0].error_code == "invalid_output"
    assert long_name not in fake.calls[0]["prompt"]


# ── 리뷰 반영(b2) ─────────────────────────────────────────────


def _rename(client, headers, name=None, display=None):
    from app.features.family_group.models import GroupMember, User

    uid, gid = _ids(client, headers)
    with SessionLocal() as db:
        if name:
            db.get(User, uid).name = name
        if display:
            db.get(GroupMember, (gid, uid)).display_name = display
        db.commit()


def test_first_name_only_title_survives_restoration_to_the_full_name(client, ready, fake, records):
    """제목에는 성을 뗀 이름('지민')이 있고 토큰을 되돌리면 대표 이름('김지민')이 된다. 그 문장을 버리면 안 된다."""
    a, _ = ready
    _rename(client, a, name="김지민")
    records.items = [SourceRecord("event", "ev-1", "지민 수학학원", date(2026, 11, 3), "15:00")]
    fake.data = {
        "title": "수학학원이 있던 주",
        "items": [{"text": "[PERSON_1]의 수학학원 일정이 15시에 있었어요", "source_ids": ["e1"]}],
    }
    body = post(client, a).json()
    assert body["status"] == "ready", body
    assert "김지민" in body["items"][0]["text"]
    assert "김지민" not in fake.calls[0]["prompt"]


def test_display_name_title_survives_restoration(client, ready, fake, records):
    a, _ = ready
    _rename(client, a, display="지니")
    records.items = [SourceRecord("event", "ev-1", "지니 축구", date(2026, 11, 3), "15:00")]
    fake.data = {
        "title": "축구가 있던 주",
        "items": [{"text": "[PERSON_1]의 축구 일정이 있었어요", "source_ids": ["e1"]}],
    }
    assert post(client, a).json()["status"] == "ready"
    assert "지니" not in fake.calls[0]["prompt"]


def test_literal_real_member_name_in_output_is_dropped(client, ready, fake, records):
    """LLM 은 실명을 모르지만, 실명을 그대로 쓴 문장은 (토큰이 아니므로) 인용 근거에 없는 이름이라 버린다."""
    a, _ = ready
    fake.data = {
        "title": "한 주",
        "items": [
            {"text": "지민 생일 파티가 있었어요", "source_ids": ["e2"]},
            {"text": "화요일 오후 2시 30분에 학교 공연이 있었어요", "source_ids": ["e1"]},
        ],
    }
    body = post(client, a).json()
    assert [i["source_ids"] for i in body["items"]] == [["e1"]]


def test_privacy_unavailable_after_claim_leaves_no_pending_row(client, ready, fake, monkeypatch):
    from app.shared.errors import ApiError

    a, _ = ready

    def down(*args, **kwargs):
        raise ApiError(503, "privacy_unavailable", "개인정보 보호 모듈을 쓸 수 없어요")

    real_new_session = generate.new_session
    monkeypatch.setattr(generate, "new_session", down)
    r = post(client, a)
    assert r.status_code == 503 and r.json()["code"] == "privacy_unavailable"
    assert rows() == [] and fake.calls == []
    monkeypatch.setattr(generate, "new_session", real_new_session)
    assert post(client, a).json()["status"] == "ready"  # 바로 다시 눌러도 된다


def test_required_ner_down_is_real_http_503_and_never_calls_the_llm(
    client, ready, fake, monkeypatch, tmp_path
):
    """실제 ner 모듈을 required + 모델 없음으로 두면(가짜 예외가 아니라) HTTP 503 privacy_unavailable 이고 외부 LLM 은 호출되지 않는다."""
    from app.shared.privacy import ner

    a, _ = ready
    monkeypatch.setattr(settings, "privacy_ner_mode", "required")
    monkeypatch.setattr(settings, "privacy_ner_model_dir", str(tmp_path / "no-model"))
    ner.reset()
    try:
        r = post(client, a)
        assert r.status_code == 503 and r.json()["code"] == "privacy_unavailable"
        assert fake.calls == []
        assert rows() == []
    finally:
        monkeypatch.undo()
        ner.reset()


def test_unexpected_error_after_the_llm_call_releases_the_claim(client, ready, fake, monkeypatch):
    from app.features.weekly_news import repository

    a, _ = ready

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(repository, "save_ok", boom)
    with pytest.raises(RuntimeError):
        post(client, a)
    assert [x.status for x in rows()] == []  # pending 이 남지 않는다
    assert len(fake.calls) == 1


def test_stale_pending_cannot_be_claimed_by_two_requests(client, ready):
    """5분 넘은 pending 을 두 요청이 같은 시각에 읽고 동시에 차지하려 해도 한 쪽만 성공한다(낙관적 조건)."""
    from app.features.weekly_news import repository

    a, _ = ready
    uid, gid = _ids(client, a)
    _put_pending(uid, gid, WED - timedelta(minutes=30))
    with SessionLocal() as db1, SessionLocal() as db2:
        stale_seen_by_2 = repository.get_for_member(db2, gid, uid, LAST_MON)
        db2.expunge(stale_seen_by_2)
        first = repository.claim(db1, gid, uid, LAST_MON, WED, generate.PENDING_STALE)
        original = repository.get_for_member
        repository.get_for_member = lambda *a, **k: stale_seen_by_2  # 두 번째는 옛 모습을 본 채로
        try:
            second = repository.claim(db2, gid, uid, LAST_MON, WED, generate.PENDING_STALE)
        finally:
            repository.get_for_member = original
    assert first is not None and second is None


@pytest.mark.parametrize("empty_materials", [False, True])
def test_request_that_loses_the_claim_returns_the_fresh_state_and_overwrites_nothing(
    client, ready, fake, records, monkeypatch, empty_materials
):
    """claim 에서 졌을 때(다른 요청이 그 사이 ok 로 만듦) 옛 상태를 돌려주거나 empty 로 덮으면 안 된다."""
    from app.features.weekly_news import repository

    a, _ = ready
    uid, gid = _ids(client, a)
    with SessionLocal() as db:
        repository.save_status(db, gid, uid, LAST_MON, "failed", "llm_failed", WED)
    if empty_materials:
        records.items = []

    def lost_claim(db, group_id, user_id, week_start, now, stale):
        with SessionLocal() as other:  # 그 사이 다른 요청이 만들었다
            repository.save_ok(
                other,
                group_id,
                user_id,
                week_start,
                body={"title": "다른 요청이 만든 뉴스", "items": []},
                sources=[],
                model="m",
                prompt_version="v1",
                input_tokens=1,
                output_tokens=1,
                now=now,
            )
        return None

    monkeypatch.setattr(repository, "claim", lost_claim)
    body = post(client, a).json()
    assert body["status"] == "ready" and body["title"] == "다른 요청이 만든 뉴스"
    assert [x.status for x in rows()] == ["ok"]
    assert fake.calls == []


def test_get_shows_a_stale_pending_row_as_not_generated(client, ready, at):
    a, _ = ready
    uid, gid = _ids(client, a)
    _put_pending(uid, gid, WED - timedelta(minutes=30))
    r = client.get(URL, params={"week_start": LAST_MON.isoformat()}, headers=a)
    assert r.json()["status"] == "not_generated"


def test_get_shows_a_fresh_pending_row_as_pending(client, ready, at):
    a, _ = ready
    uid, gid = _ids(client, a)
    _put_pending(uid, gid, WED - timedelta(seconds=30))
    r = client.get(URL, params={"week_start": LAST_MON.isoformat()}, headers=a)
    assert r.json()["status"] == "pending"


@pytest.mark.parametrize(
    "bad",
    [
        "PERSON_1이 학교 공연에 갔어요",  # 대괄호 없는 토큰 변형
        "<PERSON_1> 생일 파티가 있었어요",
        "[PHONE_1] 로 연락했어요",  # 되돌리지 않는 종류는 일반화 문구가 저장되면 안 된다
        "학교 공연 일정은 gabee-help.example 에서 확인하세요",  # 도메인
        "https://evil.example/login 에서 비밀번호를 다시 확인하세요",
        "www.evil.example 을 열어 주세요",
        "ｗｗｗ．ｅｖｉｌ．ｅｘａｍｐｌｅ 을 열어 주세요",  # 전각 문자로 쓴 링크(NFKC 로 저장되면 링크가 된다)
        "ｈｔｔｐｓ：／／ｅｖｉｌ．ｅｘａｍｐｌｅ／ｌｏｇｉｎ 에서 확인하세요",
    ],
)
def test_placeholder_variants_and_links_are_dropped(client, ready, fake, bad):
    a, _ = ready
    fake.data = {
        "title": "(PERSON_1) 소식",
        "items": [
            {"text": bad, "source_ids": ["e1"]},
            {"text": "화요일 오후 2시 30분에 학교 공연이 있었어요", "source_ids": ["e1"]},
        ],
    }
    body = post(client, a).json()
    assert body["status"] == "ready"
    assert [i["text"] for i in body["items"]] == ["화요일 오후 2시 30분에 학교 공연이 있었어요"]
    assert body["title"] == "이번 주 우리 가족"  # 토큰 변형이 든 제목은 기본 제목으로


def test_system_prompt_tells_the_model_not_to_follow_instructions_in_records():
    assert "지시" in generate.SYSTEM and "따르지" in generate.SYSTEM


def test_known_limit_non_member_names_in_titles_reach_the_llm(client, ready, fake, records):
    """한계 고정: 가명화 사전은 현재 구성원 이름뿐이라 구성원이 아닌 사람(친척·나간 구성원)의 이름은 NER 없이는 그대로 나간다."""
    a, _ = ready
    records.items = [SourceRecord("event", "ev-1", "박서연 학교 면담", date(2026, 11, 3), None)]
    post(client, a)
    assert "박서연" in fake.calls[0]["prompt"]


# ── 2026-11-11 결정 반영: 새로 만드는 것은 이번 주·지난 주만, 민감 제목 제외 ──


def test_posting_for_two_weeks_back_is_rejected_but_reading_it_is_allowed(client, ready, fake):
    a, _ = ready
    two_back = date(2026, 10, 26)
    r = post(client, a, week=two_back)
    assert r.status_code == 400 and r.json()["code"] == "news_week_too_old"
    assert fake.calls == [] and rows() == []
    got = client.get(URL, params={"week_start": two_back.isoformat()}, headers=a)
    assert got.status_code == 200 and got.json()["status"] == "not_generated"  # 읽기는 8주 전까지


def test_last_week_and_this_week_are_generatable(client, ready, fake, at):
    a, _ = ready
    assert post(client, a, week=LAST_MON).json()["status"] == "ready"
    at(datetime(2026, 11, 15, 9, 0, tzinfo=UTC))  # 일요일 18:00 KST
    assert post(client, a, week=THIS_MON).status_code == 200


def test_sensitive_titles_never_reach_the_prompt_and_all_sensitive_is_empty(
    client, ready, fake, records
):
    a, _ = ready
    records.items = [
        SourceRecord("event", "ev-1", "항암 치료 일정", date(2026, 11, 3), "10:00"),
        SourceRecord("event", "ev-2", "학교 공연", date(2026, 11, 3), "14:30"),
        SourceRecord("document", "d-1", "진단서", date(2026, 11, 5), None),
    ]
    body = post(client, a).json()
    assert body["status"] == "ready"
    sent = fake.calls[0]["prompt"]
    assert "항암" not in sent and "진단서" not in sent and "학교 공연" in sent
    assert [s["label"] for s in body["sources"]] == ["학교 공연"]
    records.items = [SourceRecord("event", "ev-1", "항암 치료 일정", date(2026, 11, 3), "10:00")]
    with SessionLocal() as db:
        db.query(MemberWeeklyNews).delete()
        db.commit()
    calls = len(fake.calls)
    assert post(client, a).json()["status"] == "empty"
    assert len(fake.calls) == calls  # 재료가 전부 민감이면 LLM 을 부르지 않는다


def test_system_prompt_forbids_asserting_that_an_appointment_was_attended():
    assert "다녀왔" in generate.SYSTEM and "단정" in generate.SYSTEM


def test_full_width_link_in_the_title_falls_back_to_the_default_title(client, ready, fake):
    a, _ = ready
    fake.data = {
        "title": "ｗｗｗ．ｅｖｉｌ．ｅｘａｍｐｌｅ 소식",
        "items": [{"text": "화요일 오후 2시 30분에 학교 공연이 있었어요", "source_ids": ["e1"]}],
    }
    body = post(client, a).json()
    assert body["status"] == "ready" and body["title"] == "이번 주 우리 가족"


def _during_the_llm_call(monkeypatch, action):
    """LLM 호출 뒤 검증 단계에서 다른 일이 일어난 것처럼 `action(uid, gid)` 를 한 번 실행한다."""
    original = generate._build_result

    def wrapped(*args, **kwargs):
        action()
        return original(*args, **kwargs)

    monkeypatch.setattr(generate, "_build_result", wrapped)


def test_leaving_the_family_during_generation_does_not_resurrect_the_news(
    client, ready, fake, monkeypatch
):
    """생성 도중(차지 뒤) 가족을 나가면 뉴스 줄이 지워진다. 이어서 저장이 줄을 새로 만들어 나간 사람의 뉴스가 남으면 안 된다."""
    from app.features.weekly_news import repository

    a, _ = ready
    uid, gid = _ids(client, a)

    def leave():
        with SessionLocal() as other:
            repository.delete_for_member(other, gid, uid)
            other.commit()

    _during_the_llm_call(monkeypatch, leave)
    body = post(client, a).json()
    assert rows() == []
    assert body["status"] != "ready" and not body.get("items")


def test_a_request_whose_claim_was_taken_over_does_not_overwrite_the_newer_one(
    client, ready, fake, monkeypatch
):
    """오래 걸린 요청의 차지를 다른 요청이 넘겨받았다면(updated_at 이 바뀜), 앞선 요청의 결과가 그 줄을 덮어쓰면 안 된다."""
    a, _ = ready

    def takeover():
        with SessionLocal() as other:
            row = other.query(MemberWeeklyNews).one()
            row.updated_at = row.updated_at + timedelta(minutes=6)
            other.commit()

    _during_the_llm_call(monkeypatch, takeover)
    body = post(client, a).json()
    only = rows()
    assert [x.status for x in only] == ["pending"] and only[0].body is None
    assert body["status"] == "pending" and not body.get("items")


def test_stored_sentence_uses_the_display_name_not_the_account_real_name(
    client, ready, fake, records
):
    """대표 이름은 표시 이름이다: 저장되는 문장에 계정 실명이 영구히 남지 않는다(나간 사람이 다른 구성원의 뉴스에 남을 때도 표시 이름)."""
    a, _ = ready
    _rename(client, a, name="김지민", display="지니")
    records.items = [SourceRecord("event", "ev-1", "지니 축구", date(2026, 11, 3), "15:00")]
    fake.data = {
        "title": "축구가 있던 주",
        "items": [{"text": "[PERSON_1]의 축구 일정이 15시에 있었어요", "source_ids": ["e1"]}],
    }
    body = post(client, a).json()
    assert body["status"] == "ready", body
    text = body["items"][0]["text"]
    assert "지니" in text and "김지민" not in text
    saved = rows()[0].body
    assert "김지민" not in str(saved)
    assert "김지민" not in fake.calls[0]["prompt"] and "지니" not in fake.calls[0]["prompt"]


def test_news_made_for_a_member_keeps_a_child_name_after_the_child_leaves(
    client, ready, fake, records
):
    """엄마의 뉴스에 자녀 이름이 들어 있어도, 자녀가 가족을 나가면 지워지는 것은 자녀 본인의 뉴스뿐이다. 엄마의 뉴스와 그 안의 이름은 그대로다."""
    from app.features.weekly_news import service

    mom, child = ready
    _rename(client, child, display="하늘")
    records.items = [SourceRecord("event", "ev-1", "하늘 축구", date(2026, 11, 3), "15:00")]
    fake.data = {
        "title": "축구가 있던 주",
        "items": [{"text": "[PERSON_1]의 축구 일정이 15시에 있었어요", "source_ids": ["e1"]}],
    }
    assert post(client, mom).json()["status"] == "ready"
    assert post(client, child).json()["status"] == "ready"
    mom_id, gid = _ids(client, mom)
    child_id, _ = _ids(client, child)

    with SessionLocal() as db:
        service.delete_my_news_on_leave(
            db, gid, child_id
        )  # 자녀가 나간다(같은 트랜잭션에서 본인 뉴스만 삭제)
        db.commit()

    left = rows()
    assert [x.user_id for x in left] == [mom_id]
    assert "하늘" in left[0].body["items"][0]["text"]
    kept = client.get(URL, params={"week_start": LAST_MON.isoformat()}, headers=mom).json()
    assert kept["status"] == "ready" and "하늘" in kept["items"][0]["text"]
