"""평가 데이터 노출 점검(E5b-B): 단계 가드와, val·test 사례 본문이 결과·출력·로그로 새지 않는지(카나리)."""

import json
import logging
from datetime import date
from pathlib import Path

import pytest

from evals.agent_eval import exposure, runner, runs_guard
from evals.agent_eval.fake_model import call, say
from tests.agent_eval.runner_support import new_case, run

CANARY_Q = "카나리질문ZQX9031"
CANARY_E = "카나리기대ZQX7742"
CANDIDATE = "abcdef1"
SCRIPT = {
    "main": [call("ask_billing", {"question": "지출 알려줘"}), say("합계는 60,000원이에요")],
    "billing": [call("get_month_summary", {"month": "2026-10"}), say("합계는 60,000원이에요")],
}


def canary_case(case_id: str, split: str):
    return new_case(
        case_id,
        split=split,
        question=f"2026년 10월 지출 합계 알려줘 {CANARY_Q}",
        expect={
            "answer": {"contains": [CANARY_E]}
        },  # 답에 없으므로 이 사례는 실패한다(실패 경로도 본다)
    )


def every_text(root: Path) -> str:
    return "\n".join(
        p.read_text("utf-8", errors="replace") for p in sorted(root.rglob("*")) if p.is_file()
    )


# ---- 가드 ----
def test_dev_and_legacy_are_open_but_val_and_test_need_their_stage():
    exposure.require_stage("dev", None)
    exposure.require_stage("legacy", None)
    exposure.require_stage("val", "validation")
    exposure.require_stage("test", "final")
    for split, stage in [
        ("val", None),
        ("val", "final"),
        ("val", "dev"),
        ("test", None),
        ("test", "validation"),
        ("nope", "final"),
    ]:
        with pytest.raises(exposure.ExposureError):
            exposure.require_stage(split, stage)


def test_load_rows_reads_only_the_requested_split_file(monkeypatch):
    opened: list[str] = []
    real = Path.read_text

    def spy(self, *a, **k):
        opened.append(self.name)
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", spy)
    rows = exposure.load_rows("dev")
    assert rows and {r["split"] for r in rows} == {"dev"}
    assert opened == ["scenarios_dev.json"]  # val·test 파일은 열지 않았다


@pytest.mark.parametrize("split", ["val", "test"])
def test_protected_splits_are_not_opened_without_a_stage(split, monkeypatch):
    opened: list[str] = []
    real = Path.read_text
    monkeypatch.setattr(
        Path, "read_text", lambda self, *a, **k: (opened.append(self.name), real(self, *a, **k))[1]
    )
    with pytest.raises(exposure.ExposureError):
        exposure.load_rows(split)
    with pytest.raises(exposure.ExposureError):
        exposure.load_rows(split, stage="dev")
    assert opened == []  # 거부가 파일을 열기 전에 일어난다
    stage = exposure.STAGE_OF_SPLIT[split]
    assert {r["split"] for r in exposure.load_rows(split, stage=stage)} == {split}


def test_a_file_with_another_split_inside_is_refused(tmp_path):
    f = tmp_path / "scenarios_val.json"
    f.write_text(json.dumps([{"id": "x", "split": "test"}]), "utf-8")
    with pytest.raises(exposure.ExposureError):
        exposure.read_split_file(f, "val", stage="validation")


@pytest.mark.parametrize(
    ("name", "split"),
    [
        ("scenarios_val.json", "val"),
        ("scenarios_test.json", "test"),
        ("cases_val.json", "val"),
        ("cases-test.json", "test"),
        ("val.json", "val"),
        ("scenarios_dev.json", None),
        ("test_runs.json", None),
        ("validate_notes.json", None),
        ("latest.json", None),
    ],
)
def test_protected_paths_are_recognised_by_name(name, split):
    assert exposure.protected_split_of(name) == split
    if split:
        with pytest.raises(exposure.ExposureError):
            exposure.assert_open_path(name)
    else:
        assert exposure.assert_open_path(name) == Path(name)


def test_the_runner_entry_already_refuses_val_without_a_purpose_and_test_without_a_guard():
    val = [canary_case("v-1", "val")]
    with pytest.raises(runner.RunnerRefused):
        run(val, scripts={"v-1": SCRIPT})
    test = [canary_case("t-1", "test")]
    with pytest.raises(runner.RunnerRefused):
        run(test, scripts={"t-1": SCRIPT}, purpose="final")


# ---- 카나리: 결과 폴더·표준출력·로그에 val·test 사례 본문이 없다 ----
def assert_no_leak(text: str) -> None:
    assert CANARY_Q not in text and CANARY_E not in text


def test_val_case_text_does_not_reach_results_stdout_or_logs(tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    case = canary_case("v-can", "val")
    report = run([case], tmp_path, scripts={"v-can": SCRIPT}, purpose="candidate")
    print("\n".join(report.summary_lines()))
    assert report.records[0].status == "judged" and report.records[0].passed is False
    assert report.run_dir is not None and (report.run_dir / runner.REPORT_FILE).exists()
    out = capsys.readouterr()
    assert_no_leak(every_text(tmp_path))
    assert_no_leak(out.out + out.err)
    assert_no_leak(caplog.text)


def test_test_case_text_does_not_reach_results_stdout_or_logs(tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    split_file = tmp_path / "in" / "cases_test.json"
    split_file.parent.mkdir()
    case = canary_case("t-can", "test")
    split_file.write_text(json.dumps([case.model_dump(mode="json")], ensure_ascii=False), "utf-8")
    runs_file = tmp_path / "runs" / "test_runs.json"
    runs_guard.init_runs_file(runs_file)
    guarded, _ = runs_guard.load_test_cases(
        runs_file, split_file, "final-1", "final", CANDIDATE, date(2026, 11, 12)
    )
    results = tmp_path / "results"
    report = run(guarded, results, scripts={"t-can": SCRIPT}, purpose="final")
    print("\n".join(report.summary_lines()))
    assert report.records[0].status == "judged"
    out = capsys.readouterr()
    assert_no_leak(every_text(results))
    assert_no_leak(runs_file.read_text("utf-8"))  # 이력 파일에는 id·해시만 있다
    assert_no_leak(out.out + out.err)
    assert_no_leak(caplog.text)


def test_an_unsupported_or_errored_case_does_not_echo_the_question_either(tmp_path, capsys):
    unsupported = canary_case("v-un", "val")  # 가짜 모드인데 대본이 없다
    named = new_case(
        "v-named",
        split="val",
        question=f"등록해줘 {CANARY_Q}",
        expect={"calls": [{"tool": "schedule.register", "stage": "billing"}]},
    )
    report = run([unsupported, named], tmp_path, scripts={}, purpose="baseline")
    print("\n".join(report.summary_lines()))
    assert {r.status for r in report.records} == {"unsupported"}
    assert_no_leak(every_text(tmp_path))
    out = capsys.readouterr()
    assert_no_leak(out.out + out.err)


def test_the_report_and_store_keep_ids_and_numbers_not_question_or_expected_text(tmp_path):
    case = canary_case("v-keys", "val")
    report = run([case], tmp_path, scripts={"v-keys": SCRIPT}, purpose="candidate")
    saved = json.loads((report.run_dir / runner.REPORT_FILE).read_text("utf-8"))
    for row in saved["cases"]:
        assert set(row) == {
            "case_id",
            "split",
            "repeat",
            "status",
            "detail",
            "passed",
            "legacy_passed",
            "write_gate",
            "skipped_checks",
            "failure_types",
            "security_violations",
            "known_gap",
            "llm_calls",
            "tokens_in",
            "tokens_out",
            "cost_usd",
            "faults_injected",
        }  # fmt: skip  (faults_injected: 도구 오류 주입 횟수 하나뿐, 질문·답·기대 원문 없음)
    for name in ("cases.jsonl", "manifest.json", "summary.csv", "failures.csv", "usage.jsonl"):
        assert_no_leak((report.run_dir / name).read_text("utf-8"))
    line = json.loads((report.run_dir / "cases.jsonl").read_text("utf-8").splitlines()[0])
    assert "question" not in line and "expect" not in line
