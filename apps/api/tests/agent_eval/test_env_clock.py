"""고정 시계 시험(L0). 평가 프로세스 안에서만 시각이 고정되고 운영 코드는 그대로인지 본다.

기준 시각은 오늘 날짜와 겹치지 않는 과거(PAST)를 써서, 시계가 교체되지 않았는데 통과하는 일이 없게 한다."""

import re
import sys
import types
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from evals.agent_eval import clock
from evals.agent_eval.clock import KST, REFERENCE_NOW, frozen_clock

PAST = datetime(2026, 3, 2, 12, 0, tzinfo=KST)  # 월요일


def _readers():
    from app.features.ai_assistant.knowledge import rag_chat
    from app.features.billing import service as billing_service
    from app.features.family_chat import agent as chat_agent
    from app.features.schedule.agent import register
    from app.shared import ai_usage

    return rag_chat, billing_service, chat_agent, register, ai_usage


def test_every_agent_reads_the_reference_date_while_frozen():
    rag_chat, billing_service, chat_agent, register, ai_usage = _readers()
    with frozen_clock(PAST):
        assert register.today() == date(2026, 3, 2)
        assert billing_service.today_kst() == "2026-03-02"
        assert chat_agent._today().startswith("2026-03-02")  # 뒤에 요일이 붙는다
        assert "2026-03-02(월요일)" in rag_chat.today_note()
        assert ai_usage._now().date() == date(2026, 3, 2)  # DB 기본값 함수도 같은 시계를 본다


def test_time_moves_forward_but_the_date_does_not_change():
    _, _, _, _, ai_usage = _readers()
    with frozen_clock(PAST):
        stamps = [ai_usage._now() for _ in range(5)]
    assert stamps == sorted(set(stamps)) and {s.date() for s in stamps} == {date(2026, 3, 2)}


def test_the_clock_is_restored_afterwards_and_after_errors():
    _, billing_service, _, register, _ = _readers()
    with pytest.raises(ZeroDivisionError), frozen_clock(PAST):
        raise ZeroDivisionError
    assert billing_service.datetime is datetime and register.datetime is datetime
    assert datetime.now(UTC).year >= 2026 and datetime.now(UTC).date() != date(2026, 3, 2)
    with frozen_clock(PAST):  # 오류 뒤에도 다시 열 수 있다(열림 표시가 남지 않는다)
        pass


def test_parsing_helpers_keep_working_inside_the_frozen_clock():
    _, billing_service, *_ = _readers()
    with frozen_clock(PAST):
        assert billing_service.datetime.strptime("2026-11-05", "%Y-%m-%d").date() == date(
            2026, 11, 5
        )


def test_timezone_less_now_and_today_are_korean_local_time_like_the_real_ones():
    fake_datetime, fake_date = clock.make_clock(PAST)
    assert (
        fake_datetime.now().hour == 12 and fake_datetime.today().day == 2
    )  # KST 12시(UTC 03시 아님)
    assert fake_date.today() == date(2026, 3, 2)
    assert fake_datetime.utcnow().hour == 3


def test_naive_reference_time_is_rejected():
    with pytest.raises(ValueError):
        clock.make_clock(datetime(2026, 11, 10, 12, 0))


def test_the_limit_is_the_next_korean_midnight_for_any_reference_time():
    """UTC 12시(= KST 21시)에서 시작하면 3시간(10_800_000 틱) 뒤 KST 자정을 넘으므로 그 전에 멈춘다."""
    fake_datetime, _ = clock.make_clock(datetime(2026, 3, 2, 12, 0, tzinfo=UTC))
    ticks = 0
    with pytest.raises(RuntimeError, match="자정"):
        while ticks < 11_000_000:
            fake_datetime.now(UTC)
            ticks += 1
    assert 10_700_000 < ticks <= 10_800_000


def test_opening_a_clock_inside_another_is_refused():
    with frozen_clock(PAST), pytest.raises(RuntimeError, match="겹쳐"), frozen_clock(REFERENCE_NOW):
        pass


def test_a_module_imported_after_the_clock_started_is_reported_at_the_end():
    probe = types.ModuleType("app._late_probe")
    probe.datetime = datetime  # 실제 시각을 읽는 늦은 모듈
    with pytest.raises(RuntimeError, match="app._late_probe"), frozen_clock(PAST):
        sys.modules["app._late_probe"] = probe
    sys.modules.pop("app._late_probe", None)
    with frozen_clock(PAST):  # 보고한 뒤에도 시계는 정상으로 닫혔다
        pass


def test_no_app_module_reads_time_in_a_way_the_clock_cannot_replace():
    """`dt.datetime.now()` 처럼 모듈 방식으로 읽는 코드가 생기면 고정 시계가 새므로 막는다."""
    app = Path(__file__).resolve().parents[2] / "app"
    bad = re.compile(
        r"\bdt\.(datetime\.(now|utcnow|today)|date\.today)|\bdatetime\.datetime\.(now|utcnow|today)"
    )
    hits = [
        str(p.relative_to(app))
        for p in app.rglob("*.py")
        if "tests" not in p.parts and bad.search(p.read_text(encoding="utf-8"))
    ]
    assert hits == []
