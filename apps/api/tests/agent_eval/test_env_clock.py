"""고정 시계 시험(L0). 평가 프로세스 안에서만 시각이 고정되고 운영 코드는 그대로인지 본다."""

import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from evals.agent_eval import clock
from evals.agent_eval.clock import REFERENCE_NOW, frozen_clock


def _readers():
    from app.features.ai_assistant.knowledge import rag_chat
    from app.features.billing import service as billing_service
    from app.features.family_chat import agent as chat_agent
    from app.features.schedule.agent import register
    from app.shared import ai_usage

    return rag_chat, billing_service, chat_agent, register, ai_usage


def test_every_agent_reads_the_reference_date_while_frozen():
    rag_chat, billing_service, chat_agent, register, ai_usage = _readers()
    with frozen_clock():
        assert register.today() == date(2026, 11, 10)
        assert billing_service.today_kst() == "2026-11-10"
        assert chat_agent._today().startswith("2026-11-10")  # 뒤에 요일이 붙는다
        assert "2026-11-10(화요일)" in rag_chat.today_note()
        assert ai_usage._now().date() == date(2026, 11, 10)  # DB 기본값 함수도 같은 시계를 본다


def test_time_moves_forward_but_the_date_does_not_change():
    _, _, _, _, ai_usage = _readers()
    with frozen_clock():
        stamps = [ai_usage._now() for _ in range(5)]
    assert stamps == sorted(set(stamps)) and {s.date() for s in stamps} == {date(2026, 11, 10)}


def test_the_clock_is_restored_afterwards_and_after_errors():
    _, billing_service, _, register, _ = _readers()
    with pytest.raises(ZeroDivisionError), frozen_clock():
        raise ZeroDivisionError
    assert billing_service.datetime is datetime and register.datetime is datetime
    assert datetime.now(UTC).year >= 2026 and datetime.now(UTC) != REFERENCE_NOW


def test_parsing_helpers_keep_working_inside_the_frozen_clock():
    _, billing_service, *_ = _readers()
    with frozen_clock():
        assert billing_service.datetime.strptime("2026-11-05", "%Y-%m-%d").date() == date(
            2026, 11, 5
        )


def test_naive_reference_time_and_running_past_midnight_are_rejected(monkeypatch):
    with pytest.raises(ValueError):
        clock.make_clock(datetime(2026, 11, 10, 12, 0))
    monkeypatch.setattr(clock, "MAX_TICKS", 3)
    fake_datetime, _ = clock.make_clock(REFERENCE_NOW)
    for _ in range(3):
        fake_datetime.now(UTC)
    with pytest.raises(RuntimeError):
        fake_datetime.now(UTC)


def test_no_app_module_reads_time_in_a_way_the_clock_cannot_replace():
    """`dt.datetime.now()` 처럼 모듈 방식으로 읽는 코드가 생기면 고정 시계가 새므로 막는다."""
    app = Path(__file__).resolve().parents[2] / "app"
    bad = re.compile(
        r"\bdt\.(datetime\.(now|utcnow)|date\.today)|\bdatetime\.datetime\.(now|utcnow)"
    )
    hits = [
        str(p.relative_to(app))
        for p in app.rglob("*.py")
        if "tests" not in p.parts and bad.search(p.read_text(encoding="utf-8"))
    ]
    assert hits == []
