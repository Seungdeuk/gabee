"""비용·예산 시험(L0). 네트워크·LLM 없이 계산만 검증한다."""

from decimal import Decimal as D

import pytest

from evals.agent_eval.cost import (
    BASELINE_RUN_SCOPES,
    CAPS,
    LOOP_CALL_SCOPES,
    LOOP_RUN_SCOPES,
    OTHER_RUN_SCOPES,
    PRICE_SOURCE,
    BudgetExceeded,
    Ledger,
    Scope,
    call_cost,
    estimate_cost,
    token_cap_for,
)

HAIKU, SONNET, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"


def test_call_cost_uses_official_per_million_token_prices():
    assert call_cost(HAIKU, 100_000, 0) == D("0.01")
    assert call_cost(HAIKU, 0, 1_000_000) == D("0.50")
    assert call_cost(HAIKU, 1_000, 500) == D("0.00035")
    assert call_cost(SONNET, 1_000_000, 1_000_000) == D("12.00")
    assert call_cost(OPUS, 1_000_000, 1_000_000) == D("24.00")
    assert "Anthropic" in PRICE_SOURCE


def test_haiku_long_prompts_use_the_long_context_price_above_100k_input_tokens():
    assert call_cost(HAIKU, 100_000, 0) == D("0.01")  # 경계는 표준 단가
    assert call_cost(HAIKU, 100_001, 0) == D("0.0500005")
    assert call_cost(HAIKU, 100_001, 1_000_000) == D("0.0500005") + D("2.50")
    assert call_cost(SONNET, 200_000, 0) == D("0.40")  # 다른 모델은 장문 단가가 없다


def test_unknown_models_and_negative_tokens_are_rejected():
    with pytest.raises(ValueError):
        call_cost("claude-unknown", 1, 1)
    with pytest.raises(ValueError):
        call_cost(HAIKU, -1, 0)
    with pytest.raises(ValueError):
        token_cap_for(D("2"), "claude-unknown")


def test_token_cap_assumes_everything_is_output_to_stay_conservative():
    assert token_cap_for(D("2"), HAIKU) == 800_000  # 장문 단가 출력 2.50 기준
    assert token_cap_for(D("2"), SONNET) == 200_000
    assert token_cap_for(D("0.000001"), OPUS) == 0


def test_estimate_cost_multiplies_per_query_cost():
    assert estimate_cost(HAIKU, 162, 20_000, 2_000) == D("0.486")
    assert estimate_cost(HAIKU, 0, 20_000, 2_000) == 0


def test_caps_and_scope_sets_match_the_agreed_budgets():
    assert CAPS == {Scope.RUN: D(2), Scope.BASELINE: D(5), Scope.LOOP: D(15), Scope.PROJECT: D(40)}
    assert set(BASELINE_RUN_SCOPES) == {Scope.RUN, Scope.BASELINE, Scope.PROJECT}
    assert set(LOOP_RUN_SCOPES) == {Scope.RUN, Scope.LOOP, Scope.PROJECT}
    assert set(LOOP_CALL_SCOPES) == {Scope.LOOP, Scope.PROJECT}  # 후보 생성은 실행 1회 상한 밖
    assert set(OTHER_RUN_SCOPES) == {Scope.RUN, Scope.PROJECT}


def test_ledger_records_per_call_usage_and_cumulative_cost_exactly():
    ledger = Ledger(OTHER_RUN_SCOPES)
    first = ledger.record("c-1", 0, HAIKU, 1_000, 500)
    second = ledger.record("c-1", 0, HAIKU, 1_000, 500)
    other = ledger.record("c-1", 1, HAIKU, 1_000, 500)
    assert [u.call_index for u in (first, second, other)] == [0, 1, 0]
    assert second.cumulative == D("0.0007") and other.cumulative == D("0.00105")
    assert ledger.total == D("0.00105") and len(ledger.usages) == 3
    assert ledger.spent[Scope.RUN] == ledger.spent[Scope.PROJECT] == D("0.00105")
    assert set(first.as_dict()) == {
        "case_id", "repeat", "call_index", "model", "tokens_in", "tokens_out", "cost_usd", "cumulative_usd",
    }  # fmt: skip
    assert first.as_dict()["cost_usd"] == "0.00035"


def test_ledger_has_no_float_drift():
    ledger = Ledger((Scope.RUN,))
    ledger.record("c", 0, SONNET, 50_000, 0)  # 0.10달러
    ledger.record("c", 0, SONNET, 100_000, 0)  # 0.20달러
    assert ledger.total == D("0.30")  # float 이면 0.30000000000000004


def test_run_cap_is_per_runner_invocation_and_stops_after_the_call_that_crosses_it():
    ledger = Ledger(OTHER_RUN_SCOPES)
    ledger.record("c", 0, SONNET, 1_000_000, 0)  # 2달러, 상한과 같음
    with pytest.raises(BudgetExceeded) as err:
        ledger.record("c", 1, SONNET, 1_000, 0)
    assert err.value.scope is Scope.RUN and err.value.cap == D(2)
    assert len(ledger.usages) == 2  # 넘긴 호출도 기록은 남는다
    assert Ledger(OTHER_RUN_SCOPES).spent[Scope.RUN] == 0  # 새 실행은 0 에서 시작


def test_baseline_cap_accumulates_over_several_runs_through_opening():
    first = Ledger(BASELINE_RUN_SCOPES)
    first.record("c", 0, SONNET, 600_000, 0)  # 1.2달러
    second = Ledger(
        BASELINE_RUN_SCOPES, opening={Scope.BASELINE: D("4.9"), Scope.PROJECT: D("4.9")}
    )
    with pytest.raises(BudgetExceeded) as err:
        second.record(
            "c", 0, SONNET, 150_000, 0
        )  # 0.3달러: 실행 상한은 괜찮지만 베이스라인 합계가 5.2
    assert err.value.scope is Scope.BASELINE


def test_loop_calls_are_not_limited_by_the_per_run_cap_but_by_loop_and_project():
    ledger = Ledger(LOOP_CALL_SCOPES)
    ledger.record(
        "gen", 0, SONNET, 1_500_000, 0
    )  # 3달러 > 실행 1회 상한이지만 후보 생성이라 괜찮다
    assert Scope.RUN not in ledger.spent
    loop_full = Ledger(LOOP_CALL_SCOPES, opening={Scope.LOOP: D("14.9"), Scope.PROJECT: D("1")})
    with pytest.raises(BudgetExceeded) as err:
        loop_full.record("gen", 0, SONNET, 100_000, 0)  # 0.2달러 → 루프 15.1
    assert err.value.scope is Scope.LOOP
    project_full = Ledger(LOOP_CALL_SCOPES, opening={Scope.LOOP: D(1), Scope.PROJECT: D("39.9")})
    with pytest.raises(BudgetExceeded) as err:
        project_full.record("gen", 0, SONNET, 100_000, 0)
    assert err.value.scope is Scope.PROJECT


def test_opening_for_scopes_the_ledger_does_not_use_is_ignored():
    ledger = Ledger(OTHER_RUN_SCOPES, opening={Scope.LOOP: D(99), Scope.PROJECT: D(10)})
    assert Scope.LOOP not in ledger.spent and ledger.spent[Scope.PROJECT] == 10


def test_estimate_is_checked_against_every_scope_before_any_spending():
    ledger = Ledger(
        BASELINE_RUN_SCOPES, opening={Scope.BASELINE: D("4.5"), Scope.PROJECT: D("4.5")}
    )
    ledger.check_estimate(D("0.5"))  # 합계가 정확히 상한이면 괜찮다
    with pytest.raises(BudgetExceeded) as err:
        ledger.check_estimate(D("0.51"))
    assert err.value.scope is Scope.BASELINE and ledger.usages == []
    with pytest.raises(BudgetExceeded) as run_err:
        Ledger(OTHER_RUN_SCOPES).check_estimate(D("2.01"))
    assert run_err.value.scope is Scope.RUN


def test_remaining_shows_what_is_left_per_scope():
    ledger = Ledger(BASELINE_RUN_SCOPES, opening={Scope.PROJECT: D("10")})
    ledger.record("c", 0, SONNET, 100_000, 0)  # 0.2달러
    assert ledger.remaining() == {
        Scope.RUN: D("1.8"),
        Scope.BASELINE: D("4.8"),
        Scope.PROJECT: D("29.8"),
    }
