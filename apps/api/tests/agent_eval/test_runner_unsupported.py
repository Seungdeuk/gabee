"""지원하지 않는 사례는 실행하지 않고 사유와 함께 보고한다(L0): 조용히 통과·실패로 세지 않는다."""

import json

from evals.agent_eval import runner
from tests.agent_eval.runner_support import ask_billing_script, new_case, run

SCHEDULE_WRITE = {
    "calls": [{"tool": "schedule.register", "stage": "schedule"}],
    "outcome": {"can_answer": True},
}


def _run_unexecuted(case, scripts=None, tmp_path=None):
    ran = []
    report = run([case], tmp_path, scripts=scripts or {})
    ran.extend(report.fakes)
    return report, ran


def test_a_schedule_write_case_is_reported_unsupported_with_the_reason_and_is_not_run(tmp_path):
    case = new_case(
        "n-sched", agent_path="schedule", question="내일 3시 치과 등록해줘", expect=SCHEDULE_WRITE
    )
    report, ran = _run_unexecuted(case, {"n-sched": ask_billing_script()}, tmp_path)
    (rec,) = report.records
    assert rec.status == "unsupported" and "일정 쓰기" in rec.detail
    assert ran == [] and report.observations == {} and report.stored == []  # 실행하지 않았다
    assert (rec.passed, rec.legacy_passed, rec.write_gate) == (None, None, None)
    c = report.counts()
    assert (c["unsupported"], c["passed"], c["failed"]) == (1, 0, 0)
    assert report.all_counted_passed  # 지원 안 함은 실패도 통과도 아니다(따로 보고한다)
    assert "지원 안 함 1" in "\n".join(report.summary_lines())
    saved = json.loads((report.run_dir / runner.REPORT_FILE).read_text("utf-8"))
    assert (
        saved["cases"][0]["status"] == "unsupported" and "일정 쓰기" in saved["cases"][0]["detail"]
    )


def test_a_schedule_read_case_is_not_blocked_by_the_schedule_write_rule():
    case = new_case(
        "n-sched-read",
        agent_path="schedule",
        expect={"tools": {"required": ["schedule.query"]}},
    )
    assert runner.unsupported_reason(case, runner.RunOptions("r"), {"n-sched-read": {}}) is None


def test_a_schedule_write_in_a_forbidden_list_is_also_unsupported_before_running():
    """되묻기 같은 정상 동작을 호출로 알아볼 수 없으니 금지 목록에 적은 일정 쓰기도 지금은 판정할 수 없다."""
    case = new_case("n-forbid", expect={"tools": {"forbidden": ["schedule.register"]}})
    reason = runner.unsupported_reason(case, runner.RunOptions("r"), {"n-forbid": {}})
    assert reason == runner.SCHEDULE_WRITE_REASON


def test_a_run_that_observes_a_schedule_write_call_is_reported_unsupported_not_scored(monkeypatch):
    """기대하지 않았어도 관찰에 일정 쓰기 호출이 있으면(완료인지 되묻기인지 모른다) 통과·실패로 세지 않는다."""
    from app.shared.llm import eval_hook

    real = runner._ask_chat

    def with_schedule_write(case, world, session):
        got = real(case, world, session)
        eval_hook.observe_call("schedule", "schedule.register", {"title": "치과"})
        return got

    monkeypatch.setattr(runner, "_ask_chat", with_schedule_write)
    case = new_case("n-obs", expect={"outcome": {"can_answer": True}})
    report = run([case], scripts={"n-obs": ask_billing_script()})
    (rec,) = report.records
    assert rec.status == "unsupported" and "schedule.register" in rec.detail
    assert (rec.passed, rec.legacy_passed) == (None, None) and report.stored == []
    assert report.counts()["unsupported"] == 1 and ("n-obs", 0) in report.observations
    assert runner.schedule_write_calls(report.observations[("n-obs", 0)]) == ["schedule.register"]


def test_a_new_case_without_a_script_in_fake_mode_is_unsupported_not_failed():
    report, ran = _run_unexecuted(new_case("n-noscript"))
    assert (
        report.records[0].status == "unsupported"
        and "대본" in report.records[0].detail
        and ran == []
    )


def test_an_undefined_setup_seed_is_unsupported():
    case = new_case("n-seed", setup={"seed": "special"})
    reason = runner.unsupported_reason(case, runner.RunOptions("r"), {"n-seed": {}})
    assert reason and "setup.seed" in reason


def test_unsupported_cases_do_not_stop_the_run_and_the_others_are_judged():
    ok = new_case("n-ok")
    report = run(
        [new_case("n-noscript"), ok],
        scripts={"n-ok": ask_billing_script()},
    )
    assert [r.status for r in report.records] == ["unsupported", "judged"]


def test_real_mode_does_not_need_a_script_so_only_the_schedule_rule_applies():
    case = new_case("n-real")
    assert runner.unsupported_reason(case, runner.RunOptions("r", mode="real"), {}) is None
