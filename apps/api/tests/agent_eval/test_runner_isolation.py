"""사례·반복 사이의 상태 격리와 결정성(L0, 가짜 모델): DB·메모리 초안·시계·기록기·가짜 모델 상태가 새지 않고, 같은 조건이면 결과가 같다."""

from datetime import UTC

import pytest

from evals.agent_eval import runner
from evals.agent_eval.clock import REFERENCE_NOW
from tests.agent_eval.runner_support import legacy, run

CASES = ("b-total", "b-write-propose", "m-billing")


@pytest.fixture
def probes(monkeypatch):
    """각 반복의 입구 직전에 상태를 살펴보고 일부러 흔적(지출·되묻기 초안)을 남긴다."""
    seen: list[dict] = []
    real = runner._ask_legacy

    def spy(lc):
        from sqlalchemy import func, select

        from app.features.billing.models import Expense
        from app.features.schedule.agent import ask
        from app.shared import ai_guard
        from app.shared.db import SessionLocal
        from app.shared.llm import eval_hook, transport

        with SessionLocal() as db:
            traces = db.scalar(select(func.count()).where(Expense.title == "앞 사례의 지출"))
            total = db.scalar(select(func.count()).select_from(Expense))
        with ask._pending_lock:
            drafts = len(ask._pending)
        rec = eval_hook.current()
        seen.append(
            {
                "case": lc.case.id,
                "trace_expenses": traces,
                "expenses": total,
                "drafts": drafts,
                "recording": rec,
                "recorded_calls": len(rec.calls),
                "recorded_steps": rec.steps,
                "model": transport.post_messages,
                "clock_offset_ms": int(
                    (ai_guard.datetime.now(UTC) - REFERENCE_NOW).total_seconds() * 1000
                ),
            }
        )
        with SessionLocal() as db:  # 흔적을 남긴다: 다음 반복이 이것을 보면 격리가 깨진 것이다
            db.add(
                Expense(
                    id=f"trace-{len(seen)}",
                    group_id="g",
                    title="앞 사례의 지출",
                    amount=1,
                    date="2026-11-10",
                    paid_by="u",
                )
            )
            db.commit()
        with ask._pending_lock:
            ask._pending[("g", f"u{len(seen)}")] = (1e18, None)
        return real(lc)

    monkeypatch.setattr(runner, "_ask_legacy", spy)
    return seen


def test_database_and_memory_state_from_an_earlier_case_is_gone_in_the_next(probes):
    run(legacy(*CASES), repeats=2)
    assert len(probes) == 6
    assert [p["trace_expenses"] for p in probes] == [0] * 6  # 앞 반복이 만든 지출이 보이지 않는다
    assert [p["drafts"] for p in probes] == [0] * 6  # 되묻기 초안도 비워졌다
    assert len({p["expenses"] for p in probes}) == 1  # 시드는 매번 같은 크기다


def test_the_recorder_and_the_fake_model_start_fresh_for_every_case(probes):
    report = run(legacy(*CASES), repeats=2)
    recordings = [p["recording"] for p in probes]
    assert len({id(r) for r in recordings}) == 6  # 기록기는 반복마다 새로 열린다
    assert all(p["recorded_calls"] == 0 and p["recorded_steps"] == 0 for p in probes)
    models = [p["model"] for p in probes]
    assert len({id(m) for m in models}) == 6  # 전송 함수(측정기가 감싼 가짜)도 반복마다 새로 만든다
    # 가짜 모델의 대본 커서는 반복마다 처음부터다: 같은 사례의 두 반복이 같은 호출을 한다
    for case_id in CASES:
        first, second = report.fakes[(case_id, 0)], report.fakes[(case_id, 1)]
        assert first is not second and first.agents == second.agents and first.calls == second.calls
    assert all(r.status == "judged" and r.passed for r in report.records)


def test_the_clock_restarts_at_the_reference_time_for_every_iteration(probes):
    run(legacy(*CASES), repeats=2)
    offsets = [p["clock_offset_ms"] for p in probes]
    assert (
        len(set(offsets)) == 1 and 0 <= offsets[0] < 60_000
    )  # 기준 시각에서 다시 시작해 시드가 쓴 만큼만 지났다
    assert offsets[0] >= 0


def test_the_environment_is_restored_after_a_run():
    from app.shared import ai_guard
    from app.shared.config import settings
    from app.shared.llm import transport

    limits = {
        k: (v[0].per_user_per_day, v[0].per_group_per_day) for k, v in ai_guard._BUCKETS.items()
    }
    key, web, post = (
        settings.anthropic_api_key,
        settings.web_search_enabled,
        transport.post_messages,
    )
    run(legacy("b-total"))
    assert (settings.anthropic_api_key, settings.web_search_enabled) == (key, web)
    assert transport.post_messages is post
    after = {
        k: (v[0].per_user_per_day, v[0].per_group_per_day) for k, v in ai_guard._BUCKETS.items()
    }
    assert after == limits  # 평가가 올린 하루 한도는 되돌린다


def test_the_same_conditions_give_the_same_observations_and_scores():
    first = run(legacy(*CASES), run_id="d1")
    second = run(legacy(*CASES), run_id="d2")
    assert [r.as_dict() for r in first.records] == [r.as_dict() for r in second.records]
    assert {k: o.model_dump() for k, o in first.observations.items()} == {
        k: o.model_dump() for k, o in second.observations.items()
    }
    assert [u.as_dict() for u in first.ledger.usages] == [u.as_dict() for u in second.ledger.usages]
