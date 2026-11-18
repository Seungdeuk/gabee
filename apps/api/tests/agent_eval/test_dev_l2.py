"""개발셋 36건 L2 실행 시험(L0 규칙: 가짜 모델·임시 SQLite·네트워크 차단, 실제 LLM 없음).

가짜 모델 -> 실제 도구 -> 합성 DB -> 관찰 -> 채점 -> 저장 이 개발 36건 전부에서 이어지는지 본다. 정상 대본(`dev_scripts.SCRIPTS`)의 통과는 "연결이 된다"는 뜻이고
Agent 의 정확도가 아니다(`dev_scripts` 머리말). 36건 한 번이 약 2분이라(`test_runner_l2.py` 52건과 같은 관례) 모듈 안에서 두 번(정순·역순)만 돌려 공유한다.
도구 결과가 새는지는 실제 모델 실행에서는 Observation 에 도구 결과가 없어 사례 단위로 볼 수 없다(후속). 가짜 모드는 가짜 모델이 받은 도구 결과를 가지고 있어 여기서 확인한다.
"""

import csv
import json
import re

import pytest

from app.shared.llm import transport
from evals.agent_eval import case_files as cf
from evals.agent_eval import cli, dev_cases, dev_scripts, runner
from evals.agent_eval.fake_model import ScriptContext
from tests.agent_eval.runner_support import run

REVERSED_ID = "dev-l2-reversed"
NO_SCHEDULE_REPLY = "s-dev-12-toolfail-02"  # 메인의 ask_schedule 이 주입된 오류로 실패하는 사례(일정 Agent 는 불리지 않는다)


@pytest.fixture(scope="module")
def cases():
    return cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")


@pytest.fixture(scope="module")
def tripwire():
    """실제 전송 함수가 불리면 기록한다. 실행기는 가짜 모델을 끼워 넣었다 되돌리므로(`fake_model.installed`) 이 함수는 불리지 않아야 한다."""
    called: list[tuple] = []
    real = transport.post_messages

    def boom(*args, **kwargs):
        called.append((args, kwargs))
        raise AssertionError("실제 모델 전송 함수가 불렸다")

    transport.post_messages = boom
    try:
        yield called
    finally:
        transport.post_messages = real


@pytest.fixture(scope="module")
def dev_run(cases, tripwire, tmp_path_factory):
    root = tmp_path_factory.mktemp("dev-l2")
    return run(cases, root, run_id="dev-l2", scripts=dev_scripts.scripts_for("dev")), root


@pytest.fixture(scope="module")
def reversed_run(cases, tripwire):
    return run(
        list(reversed(cases)), None, run_id=REVERSED_ID, scripts=dev_scripts.scripts_for("dev")
    )


def test_all_36_dev_cases_run_end_to_end_judged_and_passed(dev_run, cases):
    report, _ = dev_run
    assert [r.case_id for r in report.records] == [c.id for c in cases] and len(cases) == 36
    c = report.counts()
    assert (c["iterations"], c["judged"], c["passed"], c["failed"]) == (36, 36, 36, 0)
    assert (c["unsupported"], c["error"], c["missing_observation"], c["halted"]) == (0, 0, 0, 0)
    assert (c["known_gap"], c["unsupported_schedule_write"], c["security_write_attempts"]) == (
        0,
        0,
        0,
    )
    assert report.all_counted_passed and report.halted is None


def test_new_cases_get_the_whole_security_policy_including_the_write_gate(dev_run):
    report, _ = dev_run
    assert {r.write_gate for r in report.records} == {"applied"}
    assert all(r.skipped_checks == () and r.legacy_passed is None for r in report.records)
    assert report.counts()["write_gate_not_evaluated"] == 0


def test_no_security_violation_and_no_real_model_call(dev_run, tripwire):
    report, _ = dev_run
    assert all(r.security_violations == () and r.failure_types == () for r in report.records)
    assert tripwire == []  # transport.post_messages(실제) 는 한 번도 불리지 않았다
    assert len(report.fakes) == 36
    # 모든 반복이 대본으로 모델 호출을 대신했다(호출 수가 기록장과 같다). 대본이 바닥나 실패한 호출은 기록장이 세지 않는다
    for r in report.records:
        fake = report.fakes[(r.case_id, r.repeat)]
        assert r.llm_calls == fake.calls - len(fake.exhausted) >= 1, r.case_id


def test_every_script_was_used_from_the_start_and_no_model_call_failed(dev_run):
    """도구 오류는 이제 실행기가 주입한다(`fault_injection`): toolfail-02 도 일정 Agent 의 모델 호출을 일부러 실패시키지 않으므로 바닥난 대본이 없다."""
    report, _ = dev_run
    exhausted = {cid: f.exhausted for (cid, _), f in report.fakes.items() if f.exhausted}
    assert exhausted == {}


def test_a_dev_case_without_a_script_is_unsupported_not_failed(cases, tripwire):
    report = run([cases[0]], None, scripts={})
    (rec,) = report.records
    assert rec.status == "unsupported" and "대본" in rec.detail
    assert report.fakes == {} and report.counts()["failed"] == 0


def test_results_are_saved_and_the_report_has_no_question_or_answer_text(dev_run, cases):
    report, root = dev_run
    run_dir = report.run_dir
    assert run_dir == root / "dev-l2"
    for name in (
        "manifest.json",
        "cases.jsonl",
        "trajectories.jsonl",
        "usage.jsonl",
        "summary.csv",
        "runner_report.json",
    ):
        assert (run_dir / name).is_file(), name
    rows = [json.loads(line) for line in (run_dir / "cases.jsonl").read_text("utf-8").splitlines()]
    assert len(rows) == 36 and all(r["passed"] for r in rows)
    assert {(r["write_gate"], tuple(r["skipped_checks"])) for r in rows} == {("applied", ())}
    manifest = json.loads((run_dir / "manifest.json").read_text("utf-8"))
    assert manifest["cases"] == 36 and manifest["calls"] == len(report.ledger.usages)
    text = (run_dir / "runner_report.json").read_text("utf-8")
    assert all(c.question not in text for c in cases) and "answer" not in text
    rows = dict(csv.reader((run_dir / "summary.csv").open(encoding="utf-8")))
    assert rows["runner.passed"] == "36" and rows["runner.unsupported"] == "0"


def test_the_same_verdicts_and_observations_in_reverse_order_no_state_leaks_between_cases(
    dev_run, reversed_run
):
    forward, _ = dev_run
    assert [r.case_id for r in reversed_run.records] == [
        r.case_id for r in reversed(forward.records)
    ]
    for rec in forward.records:
        other = next(r for r in reversed_run.records if r.case_id == rec.case_id)
        assert (other.status, other.passed, other.failure_types, other.security_violations) == (
            rec.status,
            rec.passed,
            rec.failure_types,
            rec.security_violations,
        ), rec.case_id
        a = forward.observations[(rec.case_id, 0)]
        b = reversed_run.observations[(rec.case_id, 0)]
        assert a.model_dump() == b.model_dump(), rec.case_id  # 호출·답·제안·토큰·단계까지 같다
    assert reversed_run.counts() == forward.counts()


def tool_text(report, case_id):
    return " ".join(report.fakes[(case_id, 0)].tool_results.values())


def test_the_real_tools_ran_against_the_synthetic_world(dev_run):
    """도구 결과(합성 DB 에서 읽은 값)가 모델에게 돌아갔다. 대본이 아니라 시드가 정한 값이다."""
    report, _ = dev_run
    assert "2027-11-30" in tool_text(report, "s-dev-06-docs-01")
    assert "2026-12-15" in tool_text(report, "s-dev-06-docs-02")
    assert "2026-11-11" in tool_text(report, "s-dev-06-docs-03")
    assert re.search(r'"total": 100000', tool_text(report, "s-dev-03-billing-01"))
    assert re.search(r'"total": 48000', tool_text(report, "s-dev-03-billing-03"))
    assert "30000" in tool_text(report, "s-dev-03-billing-02")
    assert "내일 오전 10시에 치과 예약했어" in tool_text(report, "s-dev-05-chat-01")
    assert "우유, 계란, 두부" in tool_text(report, "s-dev-05-chat-02")
    assert "우유 사기" in tool_text(report, "s-dev-05-chat-03")
    assert "5월 장보기" in tool_text(report, "s-dev-11-inject-01")
    assert "지민" in tool_text(report, "s-dev-07-compound-01")  # 정산 관리자
    # 일정 답의 줄은 일정 Agent 가 DB 에서 읽은 것이다(대본은 id 만 정했다)
    answer = report.observations[("s-dev-02-schedq-01", 0)].answer
    assert "2026-11-14 18:00 가족 외식" in answer
    week = report.observations[("s-dev-02-schedq-02", 0)].answer
    for line in (
        "2026-11-11 10:00 치과 진료",
        "2026-11-12 15:00 학부모 상담",
        "방 청소 부탁",
        "마트에서 쌀 사다 주기",
    ):
        assert line in week
    assert (
        "현장체험학습" not in week and "수진 요가" not in week
    )  # 비공유 일정은 도구가 주지 않는다


def test_tool_results_never_contain_what_the_viewer_must_not_see(dev_run, cases):
    """가짜 모드 사례 단위의 도구 결과 누출 검사: 가짜 모델이 받은 모든 도구 결과에 보는 사람에게 비공개인 값이 없다.

    1:1 방·다른 가족방·다른 가족 문서를 겨냥한 사례(9·10·11)의 도구가 그 범위 밖 데이터를 돌려주지 않는다는 뜻이다.
    실제 모델 실행의 사례 단위 도구 결과 검사는 Observation 에 도구 결과가 없어 후속이다(시드·도구 단위는 test_seeds_world).
    """
    report, _ = dev_run
    checked = 0
    for case in cases:
        text = tool_text(report, case.id) if (case.id, 0) in report.fakes else ""
        billing = runner.expense_titles_visible(case, report.observations.get((case.id, 0)))
        for forbidden in runner._viewer_strings(case, billing):
            assert forbidden not in text, (case.id, forbidden)
        checked += bool(text)
    assert checked >= 20  # 도구를 부른 사례는 대부분이다


def test_probing_other_families_data_returns_nothing_through_the_real_tools(dev_run):
    """다른 가족(남)의 방·일정·할 일·문서를 겨냥한 질의도 우리 가족의 도구에서는 빈 결과다(격리가 도구 수준에서 지켜진다)."""
    report, _ = dev_run
    assert '"messages": []' in tool_text(report, "s-dev-10-isolation-01")
    assert '"messages": []' in tool_text(report, "s-dev-10-isolation-02")
    assert "이웃" not in tool_text(report, "s-dev-10-isolation-03")
    assert '"messages": []' in tool_text(
        report, "s-dev-09-p1to1-01"
    )  # 1:1 방 글이 가족방 검색에 걸리지 않는다
    assert '"messages": []' in tool_text(report, "s-dev-09-p1to1-03")


def test_tool_failure_cases_record_the_error_calls(dev_run):
    report, _ = dev_run
    ob = report.observations
    assert [
        (c.name, c.is_error) for c in ob[("s-dev-12-toolfail-01", 0)].calls if c.stage == "billing"
    ] == [("get_month_summary", True)]
    assert [
        (c.name, c.is_error) for c in ob[("s-dev-12-toolfail-03", 0)].calls if c.stage == "billing"
    ] == [
        ("get_settlement", True),
        ("get_settlement", False),
    ]
    assert [(c.stage, c.name, c.is_error) for c in ob[(NO_SCHEDULE_REPLY, 0)].calls] == [
        ("main", "ask_schedule", True)
    ]


def test_the_family_expense_titles_used_to_relax_the_check_really_exist_in_the_world(
    cases, tripwire, monkeypatch
):
    found: list[str] = []
    real = runner._ask_chat

    def spying(case, world, session):
        ctx = ScriptContext()
        for title in runner.FAMILY_EXPENSE_TITLES:
            ctx.expense_id(title)  # 없으면 ScriptError
            found.append(title)
        return real(case, world, session)

    monkeypatch.setattr(runner, "_ask_chat", spying)
    run(
        [cases[2]], None, scripts=dev_scripts.scripts_for("dev")
    )  # 도구를 부르지 않는 가장 가벼운 사례
    assert found == list(runner.FAMILY_EXPENSE_TITLES)


def test_the_cli_runs_the_dev_scripts_for_a_fake_dev_split(tmp_path):
    lines: list[str] = []
    code = cli.main(
        [
            "--fake", "--split", "dev", "--dev-file", str(dev_cases.CASES_DEV_PATH),
            "--case", "s-dev-01-routing-03", "--case", "s-dev-03-billing-01",
            "--results-dir", str(tmp_path / "results"), "--run-id", "dev-cli",
        ]
    , out=lines.append)  # fmt: skip
    text = "\n".join(lines)
    assert code == 0, text
    assert "통과 2 / 실패 0" in text and "지원 안 함 0" in text
