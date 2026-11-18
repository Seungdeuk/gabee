"""도구 오류 주입 시험(L0 규칙: 가짜 모델·임시 SQLite·네트워크 차단, 실제 LLM 없음).

S2-B1 실모델 실행에서 toolfail-01·02 는 실행기가 도구 오류를 주입하지 않아(오류 0건) 기준(`확인할 수 없`)을 통과할 수 없는 구조였고, toolfail-03 의 통과도 오류 복구를 검증하지
못했다. 이 시험은 평가 전용 주입 장치(`fault_injection`)가 ① 앱의 실제 오류 처리 경로로 모델에게 오류를 전하고 ② 주입 횟수를 결과에 남기며 ③ 주입이 한 번도 없으면 통과로 세지 않고
④ 사례가 끝나면 원래대로 되돌린다는 것을 고정한다. 운영 코드(`apps/api/app/`)는 바뀌지 않는다.
"""

import json

import pytest

from app.features.ai_assistant import agents
from app.features.billing import agent as billing_agent
from app.features.billing import service as billing_service
from app.shared.errors import ApiError
from evals.agent_eval import case_files as cf
from evals.agent_eval import dev_cases, dev_scripts, fault_injection, runner
from evals.agent_eval.dev_scripts import _ask
from evals.agent_eval.fake_model import call, say
from evals.agent_eval.runner import RunnerRefused
from tests.agent_eval.runner_support import run

TF1, TF2, TF3 = ("s-dev-12-toolfail-01", "s-dev-12-toolfail-02", "s-dev-12-toolfail-03")
MARK = fault_injection.MARKER


@pytest.fixture(scope="module")
def cases():
    return {c.id: c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}


def _go(cases, case_id, scripts=None, root=None):
    scripts = scripts if scripts is not None else dev_scripts.scripts_for("dev")
    return run([cases[case_id]], root, scripts=scripts)


# ---------- 명세 ----------
def test_only_the_three_tool_failure_cases_have_fault_specs():
    assert set(fault_injection.SPECS) == {TF1, TF2, TF3}
    one, two, three = (fault_injection.specs_for(i)[0] for i in (TF1, TF2, TF3))
    assert (one.tool, one.times) == ("get_month_summary", None)  # 끝까지 실패한다(복구할 수 없다)
    assert (two.tool, two.times) == ("ask_schedule", None)
    assert (three.tool, three.times) == (
        "get_settlement",
        1,
    )  # 첫 호출만 실패하고 재시도는 성공한다
    assert fault_injection.specs_for("s-dev-03-billing-01") == ()


# ---------- 주입이 앱의 실제 오류 경로로 모델에 전달된다 ----------
def test_a_billing_tool_failure_reaches_the_model_as_a_tool_error_and_is_counted(cases):
    report = _go(cases, TF1)
    (rec,) = report.records
    obs = report.observations[(TF1, 0)]
    assert rec.status == "judged" and rec.passed is True and rec.faults_injected == 1
    assert (obs.faults_injected, obs.fault_tools) == (1, ["get_month_summary"])
    assert [(c.stage, c.name, c.is_error) for c in obs.calls if c.stage == "billing"] == [
        ("billing", "get_month_summary", True)
    ]
    fake = report.fakes[(TF1, 0)]
    assert MARK in " ".join(fake.tool_results.values())  # 모델이 받은 도구 결과가 주입한 오류다
    assert "48,000" not in obs.answer


def test_a_main_ask_schedule_failure_is_injected_without_calling_the_schedule_agent(cases):
    report = _go(cases, TF2)
    (rec,) = report.records
    obs = report.observations[(TF2, 0)]
    assert rec.status == "judged" and rec.passed is True and rec.faults_injected == 1
    assert (obs.faults_injected, obs.fault_tools) == (1, ["ask_schedule"])
    assert [(c.stage, c.name, c.is_error) for c in obs.calls] == [("main", "ask_schedule", True)]
    assert (
        report.fakes[(TF2, 0)].exhausted == []
    )  # 일정 Agent 의 모델 호출은 일어나지 않았다(예전처럼 대본이 바닥나지 않는다)
    assert MARK in " ".join(report.fakes[(TF2, 0)].tool_results.values())


def test_the_retry_after_one_failure_succeeds(cases):
    report = _go(cases, TF3)
    (rec,) = report.records
    obs = report.observations[(TF3, 0)]
    assert rec.status == "judged" and rec.passed is True and rec.faults_injected == 1
    assert [(c.name, c.is_error) for c in obs.calls if c.stage == "billing"] == [
        ("get_settlement", True),
        ("get_settlement", False),
    ]
    assert obs.fault_tools == ["get_settlement"]


# ---------- 주입이 없으면 통과로 세지 않는다 ----------
def _scripts_that_never_call(case_id, tool_free_billing=True):
    """모델이 오류가 날 도구를 아예 부르지 않고 그럴듯한 '확인할 수 없어요' 답만 하는 대본(주입 0건)."""
    return {
        case_id: {
            "main": [_ask("ask_billing", "2026년 6월 지출 합계를 알려 줘"), say("지금은 합계를 확인할 수 없어요.")],
            "billing": [say("지금은 합계를 확인할 수 없어요. 잠시 뒤에 다시 시도해 주세요.")],
        }
    }  # fmt: skip


def test_a_correct_looking_answer_without_any_injected_error_is_not_counted_as_recovery(cases):
    report = _go(cases, TF1, scripts=_scripts_that_never_call(TF1))
    (rec,) = report.records
    assert rec.status == "missing_observation" and rec.detail.startswith("fault_not_injected")
    assert rec.faults_injected == 0 and rec.passed is not True
    c = report.counts()
    assert (c["judged"], c["passed"], c["missing_observation"], c["fault_not_injected"]) == (
        0,
        0,
        1,
        1,
    )
    assert not report.all_counted_passed
    obs = report.observations[(TF1, 0)]
    assert (obs.faults_injected, obs.fault_tools) == (0, [])
    assert "확인할 수 없" in obs.answer  # 답만 보면 통과처럼 보이지만 판정하지 않는다


def test_a_case_without_a_fault_spec_is_not_affected_and_reports_none(cases):
    report = _go(cases, "s-dev-03-billing-01")
    (rec,) = report.records
    assert rec.status == "judged" and rec.passed is True and rec.faults_injected is None
    obs = report.observations[("s-dev-03-billing-01", 0)]
    assert (obs.faults_injected, obs.fault_tools) == (0, [])
    assert not any(c.is_error for c in obs.calls)


# ---------- 원복 ----------
def test_the_patches_are_undone_after_a_case_and_after_an_error():
    real_call, real_service = agents.call, billing_agent.service
    assert real_service is billing_service
    with fault_injection.injected(TF1):
        assert billing_agent.service is not real_service
    with pytest.raises(RuntimeError), fault_injection.injected(TF2):
        assert agents.call is not real_call
        raise RuntimeError("사례 도중 예외")
    assert agents.call is real_call and billing_agent.service is real_service


def test_a_case_without_a_spec_patches_nothing():
    real_call, real_service = agents.call, billing_agent.service
    with fault_injection.injected("s-dev-03-billing-01") as inj:
        assert agents.call is real_call and billing_agent.service is real_service
    assert (inj.count, inj.names) == (0, [])


def test_times_limits_the_failures_and_other_service_functions_pass_through(monkeypatch):
    monkeypatch.setattr(billing_service, "settlement", lambda *a, **k: "REAL")
    with fault_injection.injected(TF3) as inj:
        with pytest.raises(ApiError) as e:
            billing_agent.service.settlement(None, "g", "2026-11")
        assert MARK in e.value.message and e.value.code == fault_injection.CODE
        assert billing_agent.service.settlement(None, "g", "2026-11") == "REAL"  # 재시도는 원본이다
        assert billing_agent.service.today_kst is billing_service.today_kst  # 다른 속성은 위임
    assert (inj.count, inj.names) == (1, ["get_settlement"])


def test_other_agent_calls_pass_through_while_ask_schedule_is_failed(monkeypatch):
    seen = []
    monkeypatch.setattr(agents, "call", lambda *a, **k: seen.append(a[3]) or "REAL")
    with fault_injection.injected(TF2) as inj:
        assert agents.call(None, "g", None, "ask_billing", {}, None) == "REAL"
        with pytest.raises(ApiError):
            agents.call(None, "g", None, "ask_schedule", {}, None)
    assert seen == ["ask_billing"] and (inj.count, inj.names) == (1, ["ask_schedule"])


def test_a_missing_call_site_stops_the_run_instead_of_passing_silently(cases, monkeypatch):
    monkeypatch.delattr(billing_agent, "service")
    with pytest.raises(RunnerRefused, match="주입"):
        _go(cases, TF1)
    with pytest.raises(fault_injection.FaultUnavailable):
        with fault_injection.injected(TF1):
            pass


# ---------- 결과에 남는다 ----------
def test_the_injection_count_is_saved_in_every_result_file(cases, tmp_path):
    report = _go(cases, TF3, root=tmp_path)
    run_dir = report.run_dir
    row = json.loads((run_dir / "cases.jsonl").read_text("utf-8").splitlines()[0])
    assert row["faults_injected"] == 1 and row["passed"] is True
    traj = json.loads((run_dir / "trajectories.jsonl").read_text("utf-8").splitlines()[0])
    assert (traj["faults_injected"], traj["fault_tools"]) == (1, ["get_settlement"])
    rep = json.loads((run_dir / "runner_report.json").read_text("utf-8"))
    assert rep["cases"][0]["faults_injected"] == 1 and rep["counts"]["fault_not_injected"] == 0


def test_a_run_without_injection_specs_keeps_the_old_row_shape(cases, tmp_path):
    report = _go(cases, "s-dev-03-billing-01", root=tmp_path)
    row = json.loads((report.run_dir / "cases.jsonl").read_text("utf-8").splitlines()[0])
    assert "faults_injected" not in row  # 주입 명세가 없는 사례의 행은 예전 모양 그대로다


def test_old_trajectories_without_the_new_keys_still_read(tmp_path):
    from evals.agent_eval import store

    d = tmp_path / "old"
    d.mkdir()
    (d / "trajectories.jsonl").write_text(
        json.dumps({"case_id": "x", "repeat": 0, "calls": [], "answer": ""}) + "\n", "utf-8"
    )
    (row,) = store.read_trajectories(d)
    assert (row["faults_injected"], row["fault_tools"]) == (0, [])


def test_the_dev_scripts_for_the_failure_cases_use_the_injected_errors_not_a_bad_month():
    scripts = dev_scripts.scripts_for("dev")
    assert scripts[TF1]["billing"][0] == call("get_month_summary", {"month": "2026-06"})
    assert scripts[TF3]["billing"][:2] == [
        call("get_settlement", {"month": "2026-11"}),
        call("get_settlement", {"month": "2026-11"}),
    ]
    assert (
        "schedule" not in scripts[TF2]
    )  # 일정 Agent 의 모델 호출은 필요 없다(오류는 주입으로 만든다)


def test_runner_exposes_the_spec_check_used_to_refuse_a_pass_without_injection():
    assert runner.fault_not_injected_detail("get_month_summary").startswith("fault_not_injected")
