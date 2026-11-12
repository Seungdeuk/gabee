"""HTTP 입구의 예산 중단 다리(`_bridge_halts`)와 예외 종료 시 지출 보존, 모델 없이 끝난 대체 답의 처리(L0, 가짜 모델)."""

import json
from decimal import Decimal as D

import pytest

from app.shared.llm import transport
from evals.agent_eval import runner, store, usage
from evals.agent_eval.cost import Ledger, Scope
from tests.agent_eval.runner_support import legacy, new_case, run


def _ledger(cap: str) -> Ledger:
    return Ledger((Scope.RUN,), caps={Scope.RUN: D(cap)})


def test_after_a_halt_the_bridge_never_calls_the_meter_or_the_transport_again():
    halts: list = []
    calls = []
    original = transport.post_messages
    transport.post_messages = lambda body, **k: calls.append(1) or {}
    try:
        with runner._bridge_halts(halts):
            halts.append(usage.RunHalted("예산"))  # 이미 멈춘 상태
            with pytest.raises(runner._ServerHalted):
                transport.post_messages({"max_tokens": 1})  # 아주 작은 호출도 나가지 않는다
    finally:
        transport.post_messages = original
    assert calls == []


def test_a_budget_halt_through_the_http_entrance_is_a_halt_not_an_error(tmp_path):
    report = run(
        [new_case("n-halt")], tmp_path, scripts={"n-halt": {"main": []}}, ledger=_ledger("0.0001")
    )
    assert [r.status for r in report.records] == ["halted"]
    assert report.halted and report.fakes[("n-halt", 0)].calls == 0


def test_an_error_that_hides_a_halt_is_still_counted_as_a_halt(monkeypatch):
    """앱이 멈춤을 모르는 예외로 바꿔 올려도(`TestClient` 가 다시 올림) 오류가 아니라 중단이다."""

    def boom(item, world, session):
        raise RuntimeError("앱이 다른 예외로 바꿨다")

    real_bridge = runner._bridge_halts

    def bridge_that_records(halts):
        halts.append(usage.RunHalted("예산 상한"))
        return real_bridge(halts)

    monkeypatch.setattr(runner, "_ask_chat", boom)
    monkeypatch.setattr(runner, "_bridge_halts", bridge_that_records)
    report = run([new_case("n-hide")], scripts={"n-hide": {"main": []}})
    assert [r.status for r in report.records] == ["halted"]


def test_spend_is_saved_when_the_run_ends_with_an_exception(tmp_path, monkeypatch):
    items = legacy("b-total", "b-nov-total")
    real = runner._run_one
    seen = []

    def run_one(item, repeat, options, session, ledger, scripts):
        if seen:
            raise runner.RunnerAbort("privacy_unavailable: 시험")
        seen.append(1)
        return real(item, repeat, options, session, ledger, scripts)

    monkeypatch.setattr(runner, "_run_one", run_one)
    ledger = _ledger("2")
    with pytest.raises(runner.RunnerAbort):
        run(items, tmp_path, run_id="abort-1", ledger=ledger)
    assert ledger.usages  # 첫 사례는 모델을 불렀다
    manifest = json.loads((tmp_path / "abort-1" / "manifest.json").read_text("utf-8"))
    assert manifest["calls"] == len(ledger.usages)
    assert store.opening_spent(tmp_path, "other")["project"] == ledger.total


def test_an_answer_without_any_model_call_is_not_a_missing_observation_for_new_cases(
    monkeypatch,
):
    """AI 가 꺼진 가족처럼 모델을 부르지 않고 대체 답을 주는 경우는 누락이 아니다. legacy 는 여전히 누락으로 본다."""
    got = runner._Entrance("지금은 답할 수 없어요", False, [])
    monkeypatch.setattr(runner, "_ask_chat", lambda item, world, session: got)
    report = run([new_case("n-off")], scripts={"n-off": {"main": []}})
    assert report.records[0].status == "judged"
    assert report.records[0].status != "missing_observation"
