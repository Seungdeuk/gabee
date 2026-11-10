"""실행 전 비용 추정 시험(L0). 모델은 부르지 않는다."""

from decimal import Decimal as D

import pytest

from evals.agent_eval.cost import BudgetExceeded, Ledger, Scope
from evals.agent_eval.estimate import build_estimate

MODEL = "claude-haiku-5-5"


def _ledger():
    return Ledger((Scope.RUN, Scope.PROJECT), opening={Scope.PROJECT: D(0)})


def test_the_summary_shows_assumptions_cost_and_remaining_budget():
    total, text = build_estimate(
        _ledger(),
        MODEL,
        cases=52,
        repeats=2,
        calls_per_case=4,
        tokens_in_per_call=6000,
        tokens_out_per_call=800,
    )
    assert total == D(52 * 2 * 4) * (D(6000) * D("0.10") + D(800) * D("0.50")) / D(1_000_000)
    assert (
        "호출 416회" in text and "입력 6000 / 출력 800" in text and "승인" in text and MODEL in text
    )


def test_an_estimate_over_any_cap_stops_before_starting():
    with pytest.raises(BudgetExceeded):
        build_estimate(_ledger(), "claude-opus-5-5", 52, 50, 4, 20000, 4000)


def test_nonpositive_counts_and_unknown_models_are_rejected():
    with pytest.raises(ValueError):
        build_estimate(_ledger(), MODEL, 0, 1, 1, 1, 1)
    with pytest.raises(ValueError):
        build_estimate(_ledger(), "unknown-model", 1, 1, 1, 1, 1)
