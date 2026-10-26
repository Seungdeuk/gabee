"""AI 호출 한도를 기능 묶음별로 따로 세는지 시험(ai_guard.register_bucket). 실제 Anthropic 은 부르지 않는다."""

import pytest

from app.features.schedule.agent import limits
from app.shared import ai_guard
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.errors import ApiError
from app.shared.llm import client as llm


def _call():
    return {"ok": True}, llm.JsonResult(data={}, input_tokens=1, output_tokens=1, model="fake")


@pytest.fixture
def ids(client, family, monkeypatch):
    a, _, group = family
    user_id = client.get("/family-group/me", headers=a).json()["id"]
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group["id"], user_id, True)
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(settings, "ai_request_cooldown_seconds", 30)
    monkeypatch.setattr(settings, "ai_max_calls_per_user_per_day", 10)
    limits.register()
    return user_id, group["id"]


def _run(db, ids, feature, key):
    user_id, group_id = ids
    return ai_guard.run(
        db, user_id=user_id, group_id=group_id, feature=feature, cache_key=key, call=_call
    )


def test_default_cooldown_does_not_block_schedule_chat(ids):
    with SessionLocal() as db:
        _run(db, ids, "analysis", "a")  # 기본 묶음: 30초 쿨다운이 걸린다
        with pytest.raises(ApiError) as e:
            _run(db, ids, "analysis", "b")
        assert e.value.code == "ai_cooldown"
        # 일정 채팅은 따로 센다: 방금 기본 묶음을 불렀어도, 연달아 불러도 막히지 않는다
        _run(db, ids, "schedule_chat", "1")
        _run(db, ids, "schedule_chat", "2")


def test_schedule_calls_do_not_use_default_daily_quota(ids, monkeypatch):
    monkeypatch.setattr(settings, "ai_max_calls_per_user_per_day", 1)
    monkeypatch.setattr(settings, "ai_request_cooldown_seconds", 0)
    with SessionLocal() as db:
        _run(db, ids, "schedule_chat", "1")
        _run(db, ids, "schedule_chat", "2")
        _run(db, ids, "analysis", "a")  # 일정 호출이 기본 한도 1회를 쓰지 않았다
        with pytest.raises(ApiError) as e:
            _run(db, ids, "analysis", "b")
        assert e.value.code == "ai_daily_limit_user"
        user_calls, _ = ai_guard.usage_today(db, *ids)
        assert user_calls == 1  # 사용 현황(설정 화면)에도 기본 묶음만 센다


def test_card_and_chat_are_counted_separately(ids):
    ai_guard.register_bucket("schedule_card", ai_guard.Limits(0, 2, 15), limits.CARD_FEATURES)
    try:
        with SessionLocal() as db:
            _run(db, ids, "schedule_card", "1")
            _run(db, ids, "schedule_card", "2")
            with pytest.raises(ApiError) as e:
                _run(db, ids, "schedule_card", "3")
            assert e.value.code == "ai_daily_limit_user"
            _run(db, ids, "schedule_chat", "x")  # 카드 한도를 다 써도 채팅은 된다
    finally:
        limits.register()  # 원래 설정값으로 되돌린다


def test_unregistered_features_keep_default_limits(ids):
    assert ai_guard._bucket_of("analysis") == (None, None)
    assert ai_guard._bucket_of("schedule_chat")[1] == limits.CHAT_FEATURES
