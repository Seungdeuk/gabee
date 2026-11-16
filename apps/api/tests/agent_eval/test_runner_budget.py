"""예산(L0, 가짜 모델): 전체 누적과 사례별 사용량의 구분, 상한에 닿으면 다음 호출 이전에 중단, 끝난 결과는 저장."""

import json
from decimal import Decimal as D

import pytest

from evals.agent_eval.cost import Ledger, Scope, call_cost
from evals.agent_eval.fake_model import FAKE_TOKENS
from tests.agent_eval.runner_support import legacy, run

MODEL = "claude-haiku-5-5"
ONE_FAKE_CALL = call_cost(MODEL, *FAKE_TOKENS)


def _ledger(cap: str) -> Ledger:
    return Ledger((Scope.RUN,), caps={Scope.RUN: D(cap)})


def test_each_call_is_added_to_the_run_total_and_to_its_case():
    report = run(legacy("b-total", "m-billing", "m-smalltalk"), repeats=2, ledger=_ledger("2"))
    ledger = report.ledger
    assert len(ledger.usages) == 2 * (2 + 3 + 1)
    assert ledger.total == ONE_FAKE_CALL * len(
        ledger.usages
    )  # 가짜의 토큰이 결정적이라 정확히 같다
    per_case = report.per_case_usage()
    assert {k: v["calls"] for k, v in per_case.items()} == {
        "b-total": 4,
        "m-billing": 6,
        "m-smalltalk": 2,
    }
    # 반복 단위 기록도 같은 값이다
    by_iter = {(r.case_id, r.repeat): r for r in report.records}
    assert by_iter[("m-billing", 1)].llm_calls == 3
    assert by_iter[("m-billing", 1)].cost_usd == ONE_FAKE_CALL * 3
    assert sum((r.cost_usd for r in report.records), D(0)) == ledger.total
    assert [u.call_index for u in ledger.usages if (u.case_id, u.repeat) == ("m-billing", 0)] == [
        0,
        1,
        2,
    ]


def test_the_observation_counts_the_model_calls_and_tokens_from_the_meter():
    report = run(legacy("m-billing"))
    obs = report.observations[("m-billing", 0)]
    assert (obs.llm_calls, obs.tokens_in, obs.tokens_out) == (
        3,
        3 * FAKE_TOKENS[0],
        3 * FAKE_TOKENS[1],
    )
    assert obs.latency_ms == 0  # 가짜 모드는 지연을 재지 않는다(결정성)


def test_the_run_stops_before_the_call_that_could_pass_the_cap_and_nothing_is_called(tmp_path):
    report = run(legacy("b-total", "b-nov-total"), tmp_path, ledger=_ledger("0.0001"))
    assert [r.status for r in report.records] == [
        "halted"
    ]  # 첫 호출 전에 멈췄고 다음 사례는 시작하지 않았다
    assert "호출 전에 멈춘다" in report.halted
    assert (
        report.fakes[("b-total", 0)].calls == 0
    )  # 가짜(=실제 자리의) 전송 함수가 한 번도 불리지 않았다
    assert report.ledger.usages == [] and report.stored == []  # 전송 함수도 불리지 않았다
    c = report.counts()
    assert (c["halted"], c["passed"], c["failed"]) == (1, 0, 0) and not report.all_counted_passed
    saved = json.loads((report.run_dir / "runner_report.json").read_text("utf-8"))
    assert saved["budget"]["halted"] and saved["cases"][0]["status"] == "halted"


def test_finished_cases_are_saved_and_the_halted_one_is_not_counted_as_a_pass(tmp_path):
    # 호출 한 번의 최악 비용은 몇 분의 1 센트다. 상한을 그 몇 배로 잡아 몇 사례만 끝나게 한다
    report = run(
        legacy("b-total", "b-nov-total", "m-billing", "b-poisoned", "b-list"),
        tmp_path,
        ledger=_ledger("0.0025"),
    )
    statuses = [r.status for r in report.records]
    assert statuses[0] == "judged" and statuses[-1] == "halted" and len(statuses) < 5
    done = [r.case_id for r in report.records if r.status == "judged"]
    assert [s.case.id for s in report.stored] == done and done  # 끝난 사례만 저장한다
    rows = [json.loads(x) for x in (report.run_dir / "cases.jsonl").read_text("utf-8").splitlines()]
    assert [r["case_id"] for r in rows] == done
    halted_id = report.records[-1].case_id
    assert halted_id not in {r["case_id"] for r in rows}
    cap = D("0.0025")
    assert report.ledger.total <= cap  # 상한 안에서 멈췄다(넘기는 호출은 하지 않았다)
    assert report.halted and not report.all_counted_passed


def test_an_unpriced_model_halts_the_run_instead_of_being_swallowed(monkeypatch):
    from evals.agent_eval import fake_model

    monkeypatch.setattr(fake_model, "DEFAULT_MODEL", "mystery-model")
    from app.shared.config import settings

    monkeypatch.setattr(settings, "llm_model", "mystery-model")
    report = run(legacy("b-total"), ledger=_ledger("2"))
    assert [r.status for r in report.records] == ["halted"]
    assert "단가를 모르는 모델" in report.halted


@pytest.mark.parametrize("mode", ["fake"])
def test_fake_runs_do_not_count_toward_the_project_total(mode):
    from evals.agent_eval import runner

    ledger = runner.default_ledger(mode)
    assert tuple(ledger.scopes) == (Scope.RUN,)


def test_a_halted_run_with_no_finished_case_still_records_its_spend_for_the_cumulative_total(
    tmp_path,
):
    """첫 사례의 두 번째 호출에서 멈춰 저장할 사례가 없어도, 이미 쓴 비용이 다음 실행의 누적에 합쳐져야 한다."""
    from evals.agent_eval import store

    found = None
    for i, cap in enumerate(("0.0004", "0.0006", "0.0008", "0.001", "0.0012", "0.0015")):
        root = tmp_path / f"r{i}"
        report = run(legacy("b-total"), root, run_id="halt-1", ledger=_ledger(cap))
        if report.halted and report.ledger.usages and not report.stored:
            found = (root, report)
            break
    assert found, "호출 한 번은 하고 다음 호출 전에 멈추는 상한을 찾지 못했다"
    root, report = found
    spent = store.opening_spent(root, "other")
    assert spent["project"] == report.ledger.total > 0  # 지출이 manifest 로 남았다
    manifest = json.loads((report.run_dir / "manifest.json").read_text("utf-8"))
    assert manifest["calls"] == len(report.ledger.usages) and manifest["cases"] == 0
    assert (report.run_dir / "usage.jsonl").is_file() and (
        report.run_dir / "runner_report.json"
    ).is_file()


def test_a_run_with_no_spend_and_nothing_to_store_leaves_only_the_runner_report(tmp_path):
    report = run(legacy("b-total"), tmp_path, ledger=_ledger("0.0001"))  # 첫 호출 전에 멈춘다
    assert not report.ledger.usages
    assert [p.name for p in report.run_dir.iterdir()] == ["runner_report.json"]
