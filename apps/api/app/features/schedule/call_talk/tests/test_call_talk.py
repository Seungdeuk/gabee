"""전화 이야깃거리 시험. 실제 Anthropic 은 부르지 않고 llm.complete_json 을 가짜로 바꾼다
(모델의 정확도가 아니라 입력 구성, 한도·캐시, 검증, 안부 문구 대체를 확인한다)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.shared import ai_guard
from app.shared.ai_usage import AiInflight, AiResultCache, AiUsageLog
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm

from ...constants import SUGGEST_GREETING
from ...models import CheckSuggestion
from .. import service

GOOD = {"say": "오늘 약을 챙기셨어요.", "ask": "컨디션은 어떠신지 여쭤보세요."}


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.data = dict(GOOD)
        self.error = None

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema, **kw})
        if self.error:
            raise self.error
        return llm.JsonResult(data=self.data, input_tokens=100, output_tokens=20, model="fake")


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(llm, "complete_json", f)
    monkeypatch.setattr(llm, "available", lambda: True)
    return f


@pytest.fixture
def setup(client, family):
    """(요청자 헤더, 대상 헤더, 대상 id). 가족 AI 동의는 켜 둔다."""
    a, b, group = family
    me = client.get("/family-group/me", headers=a).json()["id"]
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group["id"], me, True)
    target = client.get("/family-group/me", headers=b).json()["id"]
    return a, b, target


def _habit(client, headers, name, **fields) -> dict:
    r = client.post("/schedule/check/items", json={"name": name, **fields}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _talk(client, headers, target):
    r = client.post(f"/schedule/check/members/{target}/call-talk", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _greetings(*contents):
    with SessionLocal() as db:
        db.add_all(CheckSuggestion(category=SUGGEST_GREETING, content=c) for c in contents)
        db.commit()


def _usage_rows(calls_only: bool = True) -> int:
    """사용 기록 수(기본은 실제로 모델을 부른 줄만, 캐시 적중 줄은 제외)."""
    with SessionLocal() as db:
        query = (
            select(func.count())
            .select_from(AiUsageLog)
            .where(AiUsageLog.feature == service.FEATURE)
        )
        if calls_only:
            query = query.where(AiUsageLog.api_calls > 0)
        return db.scalar(query)


def test_public_habit_gives_one_ai_pair(client, setup, fake):
    a, b, target = setup
    pill = _habit(client, b, "약 먹기")
    client.put(f"/schedule/check/items/{pill['id']}/entry", json={"done": True}, headers=b)
    body = _talk(client, a, target)
    assert body == {"source": "ai", "reason": "", "points": [GOOD]}
    call = fake.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["schema"]["additionalProperties"] is False
    assert call["prompt"].startswith("오늘 데일리 체크\n- 약 먹기: 완료(")
    assert "횟수 습관이 목표에 못 미친다고" in call["system"]


def test_private_habit_is_not_sent(client, setup, fake):
    a, b, target = setup
    _habit(client, b, "비밀 습관", shared=False)
    _habit(client, b, "산책")
    _talk(client, a, target)
    assert "비밀 습관" not in fake.calls[0]["prompt"] and "산책" in fake.calls[0]["prompt"]


def test_avoid_habit_is_marked_and_count_state_shown(client, setup, fake):
    a, b, target = setup
    _habit(client, b, "야식 안 먹기")
    water = _habit(client, b, "물 마시기", kind=2, goal=8, unit="잔")
    client.put(f"/schedule/check/items/{water['id']}/entry", json={"count": 3}, headers=b)
    _talk(client, a, target)
    prompt = fake.calls[0]["prompt"]
    assert "- 야식 안 먹기 [줄이는 습관]: 아직" in prompt
    assert "- 물 마시기: 3/8잔" in prompt and "물 마시기 [줄이는" not in prompt


def test_no_habits_gives_greeting_without_calling_model(client, setup, fake):
    a, b, target = setup
    _greetings("요즘 어떻게 지내세요?", "식사는 잘 챙기고 계세요?", "날씨가 좋네요.")
    _habit(client, b, "비밀 습관", shared=False)
    body = _talk(client, a, target)
    assert body["source"] == "greeting" and body["reason"] == "no_habits"
    assert 1 <= len(body["points"]) <= 2 and all(
        p["ask"] == "" and p["say"] for p in body["points"]
    )
    assert fake.calls == [] and _usage_rows(False) == 0


def test_no_greeting_rows_gives_empty_points(client, setup, fake):
    a, _b, target = setup
    body = _talk(client, a, target)
    assert body == {"source": "greeting", "reason": "no_habits", "points": []}


def test_same_state_reuses_result_changed_state_calls_again(client, setup, fake):
    a, b, target = setup
    water = _habit(client, b, "물 마시기", kind=2, goal=8, unit="잔")
    _talk(client, a, target)
    again = _talk(client, a, target)
    assert again["source"] == "ai" and len(fake.calls) == 1 and _usage_rows() == 1
    client.put(f"/schedule/check/items/{water['id']}/entry", json={"count": 2}, headers=b)
    _talk(client, a, target)
    assert len(fake.calls) == 2


def test_cache_expires_after_default_ttl_and_then_counts(client, setup, fake, monkeypatch):
    a, b, target = setup
    _habit(client, b, "산책")
    _talk(client, a, target)
    later = datetime.now(UTC) + timedelta(seconds=settings.ai_result_cache_ttl_seconds + 60)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return later

    monkeypatch.setattr(ai_guard, "datetime", Later)
    assert _talk(client, a, target)["source"] == "ai"
    assert len(fake.calls) == 2 and _usage_rows() == 2


def test_group_busy_gives_error_greeting(client, family, setup, fake):
    a, b, target = setup
    _habit(client, b, "산책")
    _greetings("안녕하세요?")
    group_id = family[2]["id"]
    with SessionLocal() as db:
        for slot in range(max(1, settings.ai_max_concurrent_requests_per_group)):
            db.add(
                AiInflight(
                    group_id=group_id,
                    slot=slot,
                    token="t",
                    user_id=target,
                    feature="other",
                    started_at=datetime.now(UTC),
                )
            )
        db.commit()
    body = _talk(client, a, target)
    assert body["source"] == "greeting" and body["reason"] == "error"
    assert fake.calls == []


def test_user_daily_limit_gives_greeting_and_cached_does_not_count(client, setup, fake):
    a, b, target = setup
    water = _habit(client, b, "물 마시기", kind=2, goal=20, unit="잔")
    _greetings("안녕하세요?")
    for n in range(10):
        client.put(f"/schedule/check/items/{water['id']}/entry", json={"count": n}, headers=b)
        assert _talk(client, a, target)["source"] == "ai"
    assert _talk(client, a, target)["source"] == "ai"  # 캐시된 것은 세지 않는다
    assert len(fake.calls) == 10
    client.put(f"/schedule/check/items/{water['id']}/entry", json={"count": 15}, headers=b)
    body = _talk(client, a, target)
    assert body["source"] == "greeting" and body["reason"] == "limit"
    assert len(fake.calls) == 10


def test_consent_off_gives_greeting_and_no_usage(client, family, fake):
    a, b, _g = family
    target = client.get("/family-group/me", headers=b).json()["id"]
    _habit(client, b, "산책")
    body = _talk(client, a, target)
    assert body["source"] == "greeting" and body["reason"] == "no_consent"
    assert fake.calls == [] and _usage_rows(False) == 0


@pytest.mark.parametrize(
    "data",
    [
        {"say": "가" * 41, "ask": "괜찮아요."},
        {"say": "괜찮아요.", "ask": "나" * 41},
        {"say": "  ", "ask": "괜찮아요."},
        {"say": "괜찮아요."},
        {"say": 1, "ask": "x"},
    ],
)
def test_bad_model_output_gives_error_greeting(client, setup, fake, data):
    a, b, target = setup
    _habit(client, b, "산책")
    fake.data = data
    body = _talk(client, a, target)
    assert body["source"] == "greeting" and body["reason"] == "error"
    with SessionLocal() as db:
        assert (
            db.scalar(select(func.count()).select_from(AiResultCache)) == 0
        )  # 잘못된 결과는 저장하지 않는다


def test_model_failure_gives_error_greeting(client, setup, fake):
    a, b, target = setup
    _habit(client, b, "산책")
    fake.error = llm.LLMUnavailable("down")
    body = _talk(client, a, target)
    assert body["source"] == "greeting" and body["reason"] == "error"


def test_forty_chars_pass_and_quotes_newlines_are_cleaned(client, setup, fake):
    a, b, target = setup
    _habit(client, b, "산책")
    fake.data = {"say": '"오늘 산책을\n하셨어요."', "ask": "가" * 40}
    body = _talk(client, a, target)
    assert body["source"] == "ai"
    assert body["points"][0] == {"say": "오늘 산책을 하셨어요.", "ask": "가" * 40}


def test_other_group_target_is_404(client, setup, other_family, fake):
    a, _b, _t = setup
    outsider = client.get("/family-group/me", headers=other_family).json()["id"]
    r = client.post(f"/schedule/check/members/{outsider}/call-talk", headers=a)
    assert r.status_code == 404 and fake.calls == []


def test_prompt_has_no_names_or_relations(client, setup, fake):
    a, b, target = setup
    _habit(client, b, "산책")
    _talk(client, a, target)
    for word in ("수진", "지민", "엄마", "아빠", "할머니"):
        assert word not in fake.calls[0]["prompt"]
