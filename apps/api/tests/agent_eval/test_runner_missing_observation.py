"""관찰 누락은 명시적 실패다(L0, 가짜 모델): 기록이 0건이면 통과로 세지 않는다."""

import json
import threading

from evals.agent_eval import runner
from evals.agent_eval.runner import _Entrance
from tests.agent_eval.runner_support import legacy, run


def test_a_run_where_nothing_was_recorded_is_a_missing_observation_failure(monkeypatch, tmp_path):
    """Agent 를 부르지 않은 입구(기록도, 모델 호출도 없음)는 정상 답이 있어도 관찰 누락 오류다."""
    monkeypatch.setattr(runner, "_ask_legacy", lambda lc: _Entrance("60,000원이에요", True, []))
    report = run(legacy("b-total", "b-nov-total"), tmp_path)
    assert [r.status for r in report.records] == ["missing_observation"] * 2
    assert all(
        r.passed is None and r.legacy_passed is None for r in report.records
    )  # 통과로 세지 않는다
    c = report.counts()
    assert (c["missing_observation"], c["passed"], c["failed"], c["judged"]) == (2, 0, 0, 0)
    assert not report.all_counted_passed
    assert "모델을 한 번도 부르지 않았고" in report.records[0].detail
    assert "관찰 누락 2" in "\n".join(report.summary_lines())
    # 저장된 결과에서도 실패이고, 어떤 부분도 통과한 것으로 적히지 않는다
    rows = [json.loads(x) for x in (report.run_dir / "cases.jsonl").read_text("utf-8").splitlines()]
    assert [r["passed"] for r in rows] == [False, False]
    assert [(r["tools_ok"], r["outcome_ok"], r["answer_ok"]) for r in rows] == [(False,) * 3] * 2


def test_a_lost_recorder_is_caught_even_though_the_model_was_called(monkeypatch):
    """컨텍스트를 복사하지 않은 스레드에서 Agent 를 부르면 기록기가 비는데 측정기는 모델 호출을 센다."""
    real = runner._ask_legacy
    box = {}

    def in_raw_thread(lc):
        t = threading.Thread(target=lambda: box.setdefault("got", real(lc)))
        t.start()
        t.join()
        return box["got"]

    monkeypatch.setattr(runner, "_ask_legacy", in_raw_thread)
    report = run(legacy("b-total"))
    (rec,) = report.records
    assert rec.status == "missing_observation" and rec.passed is None
    assert "기록기가 비었는데 모델 호출은 2회" in rec.detail
    assert report.fakes[("b-total", 0)].calls == 2  # 모델은 실제로 불렸다(그래서 누락이다)


def test_a_normal_run_with_no_tool_call_is_not_a_missing_observation():
    """도구 없이 모델이 직접 답한 사례는 모델 단계가 기록되므로 누락이 아니다."""
    report = run(legacy("m-smalltalk"))
    (rec,) = report.records
    assert rec.status == "judged" and rec.passed is True
    assert report.observations[("m-smalltalk", 0)].calls == []
    assert report.observations[("m-smalltalk", 0)].steps == 1


def test_an_error_inside_one_case_is_reported_and_does_not_stop_the_others(monkeypatch):
    real = runner._ask_legacy

    def flaky(lc):
        if lc.case.id == "b-total":
            raise RuntimeError("입구 오류")
        return real(lc)

    monkeypatch.setattr(runner, "_ask_legacy", flaky)
    report = run(legacy("b-total", "b-nov-total"))
    assert [r.status for r in report.records] == ["error", "judged"]
    assert report.records[0].passed is None and "RuntimeError" in report.records[0].detail
    assert report.counts()["error"] == 1 and not report.all_counted_passed
