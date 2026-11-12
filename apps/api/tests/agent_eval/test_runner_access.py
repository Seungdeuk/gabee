"""분할 접근 제한과 실제 모델 승인 조건(L0, 가짜 모델): val·test 는 규칙을 거쳐야 돌고, 어긴 호출은 거부된다."""

import json
from datetime import date
from decimal import Decimal as D

import pytest

from evals.agent_eval import runs_guard
from evals.agent_eval.cost import Ledger, Scope
from evals.agent_eval.runner import RunnerRefused, RunOptions, run_cases
from tests.agent_eval.runner_support import ask_billing_script, legacy, new_case, run

SCRIPT = ask_billing_script()


def _test_cases(*ids):
    return [new_case(i, split="test") for i in ids]


@pytest.fixture
def guard(tmp_path):
    """이력 파일과 테스트 분할 파일(합성 사례 둘)."""
    runs = tmp_path / "test_runs.json"
    runs_guard.init_runs_file(runs)
    split = tmp_path / "test.json"
    split.write_text(
        json.dumps([c.model_dump(mode="json") for c in _test_cases("t-1", "t-2")]), encoding="utf-8"
    )
    return runs, split


def _guarded(guard, run_id="final-1", purpose="baseline"):
    runs, split = guard
    return runs_guard.load_test_cases(runs, split, run_id, purpose, "abc1234", date(2026, 11, 11))[
        0
    ]


def test_a_plain_list_of_test_cases_is_refused():
    with pytest.raises(RunnerRefused, match="GuardedCases"):
        run(_test_cases("t-1"), scripts={"t-1": SCRIPT})


def test_a_mixed_or_empty_or_duplicated_list_is_refused():
    with pytest.raises(RunnerRefused, match="섞여"):
        run([new_case("a", split="dev"), new_case("b", split="val")])
    with pytest.raises(RunnerRefused, match="하나도"):
        run([])
    with pytest.raises(RunnerRefused, match="겹친다"):
        run([new_case("a"), new_case("a")], scripts={"a": SCRIPT})


def test_validation_cases_need_a_stated_purpose():
    val = [new_case("v-1", split="val")]
    with pytest.raises(RunnerRefused, match="목적"):
        run(val, scripts={"v-1": SCRIPT})
    with pytest.raises(RunnerRefused, match="목적"):
        run(val, scripts={"v-1": SCRIPT}, purpose="whatever")
    report = run(val, scripts={"v-1": SCRIPT}, purpose="candidate")
    assert report.records[0].status == "judged"


def test_dev_and_legacy_cases_run_freely():
    assert (
        run([new_case("d-1", split="dev")], scripts={"d-1": SCRIPT}).records[0].status == "judged"
    )
    assert run(legacy("b-total")).records[0].status == "judged"


def test_test_cases_run_only_through_the_guard_and_the_history_file_records_them(guard, tmp_path):
    runs, _ = guard
    cases = _guarded(guard)
    assert runs_guard.status(runs, "final-1") == {"t-1": "pending", "t-2": "pending"}
    report = run(cases, tmp_path / "out", run_id="final-1", scripts={"t-1": SCRIPT, "t-2": SCRIPT})
    assert [r.status for r in report.records] == ["judged", "judged"]
    assert {r.split for r in report.records} == {"test"}
    assert runs_guard.status(runs, "final-1") == {"t-1": "done", "t-2": "done"}


def test_a_baseline_run_cannot_be_started_twice_and_finished_cases_are_not_rerun(guard, tmp_path):
    runs, split = guard
    first = _guarded(guard)
    run(first, tmp_path / "o1", run_id="final-1", scripts={"t-1": SCRIPT, "t-2": SCRIPT})
    with pytest.raises(runs_guard.TestRunsError, match="한 번뿐"):
        _guarded(guard, run_id="other-run")  # 같은 목적의 새 실행 id 는 예약할 수 없다
    again = _guarded(guard)  # 같은 run_id 로 이어서 하면 pending 이 없다
    report = run(again, tmp_path / "o2", run_id="final-1b", scripts={})
    assert report.records == []  # 이미 평가한 테스트 사례를 다시 평가하지 않는다


def test_a_halted_test_case_stays_started_so_it_is_not_rerun_after_seeing_its_result(
    guard, tmp_path
):
    runs, _ = guard
    cases = _guarded(guard)
    tiny = Ledger((Scope.RUN,), caps={Scope.RUN: D("0.0001")})
    report = run(cases, tmp_path / "o", run_id="final-1", scripts={"t-1": SCRIPT}, ledger=tiny)
    assert [r.status for r in report.records] == ["halted"]
    assert runs_guard.status(runs, "final-1") == {"t-1": "started", "t-2": "pending"}
    resumed = _guarded(guard)
    assert resumed.interrupted == ["t-1"] and resumed.ids() == [
        "t-2"
    ]  # 끊긴 사례는 다시 돌리지 않는다


def test_the_real_mode_needs_an_approved_amount_that_covers_the_ledger_cap():
    cases = [new_case("d-1")]
    unlimited = Ledger((Scope.RUN,))  # 기본 상한 2달러
    with pytest.raises(RunnerRefused, match="승인"):
        run_cases(cases, RunOptions("r", mode="real"), ledger=unlimited)
    with pytest.raises(RunnerRefused, match="승인"):
        run_cases(cases, RunOptions("r", mode="real", approved_usd=D(0)), ledger=unlimited)
    with pytest.raises(RunnerRefused, match="승인한 금액보다 크다"):
        run_cases(cases, RunOptions("r", mode="real", approved_usd=D("1")), ledger=unlimited)


def test_zero_repeats_are_refused():
    with pytest.raises(RunnerRefused, match="반복"):
        run(legacy("b-total"), repeats=0)
