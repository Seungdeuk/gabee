"""L2 실행기 전체 연결 시험(L0 규칙: 가짜 모델·임시 SQLite·네트워크 차단, 실제 LLM 없음).

가짜 모델 -> 실제 도구 -> 합성 DB -> 관찰 -> 채점 -> 저장 이 기존 52건 전부에서 이어지는지 본다. 가짜 대본의 최종 답은 사례의 기대 문구를 담으므로
이 통과는 "연결이 된다"는 뜻이고 Agent 의 정확도가 아니다(`fake_model` 머리말). 기대값과 채점은 바꾸지 않았다: 대본이 기대를 못 채우면 아래의 마지막 시험처럼
그대로 실패로 나온다.
"""

import csv
import json
import re

import pytest

from evals.agent_eval import adapter
from evals.agent_eval.fake_model import call, say
from tests.agent_eval.runner_support import legacy, run


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    root = tmp_path_factory.mktemp("l2-results")
    return run(adapter.load_legacy_cases(), root, run_id="l2-all"), root


def _rec(full_run, case_id):
    return next(r for r in full_run[0].records if r.case_id == case_id)


def test_all_52_legacy_cases_run_end_to_end_and_none_is_unsupported_or_missing(full):
    report, _ = full
    ids = [lc.case.id for lc in adapter.load_legacy_cases()]
    assert len(ids) == 52 and [r.case_id for r in report.records] == ids
    c = report.counts()
    assert c["iterations"] == c["judged"] == 52
    assert (c["unsupported"], c["missing_observation"], c["error"], c["halted"]) == (0, 0, 0, 0)
    # 가짜 대본이 기대를 채우므로 52건 모두 통과한다(연결 시험). 통과를 만들려고 기대값·채점을 바꾸지 않았다
    assert (c["passed"], c["failed"], c["legacy_passed"], c["legacy_failed"]) == (52, 0, 52, 0)
    assert c["write_gate_not_evaluated"] == 52 and report.all_counted_passed


def test_every_run_used_its_script_from_the_start_without_running_out(full):
    report, _ = full
    assert len(report.fakes) == 52
    assert all(f.exhausted == [] and f.calls >= 1 for f in report.fakes.values())
    assert all(r.llm_calls == report.fakes[(r.case_id, r.repeat)].calls for r in report.records)


def test_the_real_tools_ran_against_the_synthetic_database(full):
    """도구 결과(합성 DB 에서 읽은 값)가 모델에게 돌아갔고, 쓰기 '제안'은 서버가 DB 값으로 만든 문장이다."""
    report, _ = full
    results = lambda cid: " ".join(report.fakes[(cid, 0)].tool_results.values())  # noqa: E731
    assert re.search(r"60,?000", results("b-total"))
    assert re.search(r"86,?000", results("b-nov-total"))
    assert re.search(r"30,?000", results("b-child-own-allowance"))
    proposals = lambda cid: report.observations[(cid, 0)].proposals  # noqa: E731
    assert proposals("b-delete-own") == ["지출 삭제: 치과 진료 45,000원 (2026-06-15)"]
    assert proposals("b-update-amount") == ["지출 수정: 치과 진료 — 금액 45,000원 → 50,000원"]
    assert proposals("b-allowance-approve-amount") == [
        "용돈 요청 승인: 민수 3,000원 (요청 5,000원)"
    ]
    assert proposals("b-paid-propose")[0].startswith("송금 완료 표시: 수진 → 지민")
    assert len(proposals("b-write-over-limit")) == 3  # 한 답변에 최대 3건
    assert (
        proposals("m-write-billing") and len(proposals("m-write-billing")) == 1
    )  # 메인 경로의 제안


def test_tools_that_the_services_refuse_are_recorded_as_errors_and_make_no_proposal(full):
    report, _ = full
    for case_id, tool in (
        ("b-update-settled", "propose_update_expense"),
        ("b-delete-others", "propose_delete_expense"),
        ("b-allowance-not-manager", "propose_decide_allowance_request"),
        ("b-write-split-unknown", "propose_add_expense"),
    ):
        obs = report.observations[(case_id, 0)]
        assert obs.proposals == [] and [c.is_error for c in obs.calls if c.name == tool] == [True]


def test_the_main_path_records_both_stages_and_billing_cases_record_only_billing(full):
    report, _ = full
    obs = report.observations
    assert [(c.stage, c.name) for c in obs[("m-billing", 0)].calls] == [
        ("billing", "get_month_summary"),
        ("main", "ask_billing"),
    ]
    assert {c.stage for c in obs[("b-total", 0)].calls} == {"billing"}
    assert obs[("m-smalltalk", 0)].calls == [] and obs[("m-smalltalk", 0)].llm_calls == 1


def test_results_are_saved_with_the_allowed_fields_and_the_runner_report_has_no_text(full):
    report, root = full
    run_dir = report.run_dir
    assert run_dir == root / "l2-all"
    for name in (
        "manifest.json",
        "cases.jsonl",
        "trajectories.jsonl",
        "usage.jsonl",
        "summary.csv",
        "runner_report.json",
    ):
        assert (run_dir / name).is_file(), name
    cases = [json.loads(line) for line in (run_dir / "cases.jsonl").read_text("utf-8").splitlines()]
    assert len(cases) == 52 and all(c["passed"] for c in cases)
    manifest = json.loads((run_dir / "manifest.json").read_text("utf-8"))
    assert manifest["cases"] == 52 and manifest["calls"] == len(report.ledger.usages)
    text = (run_dir / "runner_report.json").read_text("utf-8")
    saved = json.loads(text)
    assert [c["case_id"] for c in saved["cases"]] == [r.case_id for r in report.records]
    # 질문·답 같은 본문은 넣지 않는다
    for lc in adapter.load_legacy_cases():
        assert lc.case.question not in text
    assert "answer" not in text and "question" not in text
    rows = dict(csv.reader((run_dir / "summary.csv").open(encoding="utf-8")))
    assert rows["runner.passed"] == "52" and rows["runner.write_gate_not_evaluated"] == "52"


def test_per_case_usage_is_separate_from_the_run_total(full):
    report, _ = full
    per_case = report.per_case_usage()
    assert set(per_case) == {r.case_id for r in report.records}
    assert sum(row["calls"] for row in per_case.values()) == len(report.ledger.usages)
    assert sum(float(row["cost_usd"]) for row in per_case.values()) == pytest.approx(
        float(report.ledger.total)
    )
    assert per_case["m-billing"]["calls"] == 3 and per_case["b-total"]["calls"] == 2
    saved = json.loads((report.run_dir / "runner_report.json").read_text("utf-8"))
    assert saved["budget"]["per_case"]["b-total"]["calls"] == 2


def test_a_script_that_does_not_meet_the_expectation_fails_without_changing_the_scoring():
    script = {
        "billing": [call("get_month_summary", {"month": "2026-10"}), say("합계는 잘 모르겠어요")]
    }
    report = run(legacy("b-total"), scripts={"b-total": script})
    (rec,) = report.records
    assert rec.status == "judged" and (rec.passed, rec.legacy_passed) == (False, False)
    assert report.counts()["failed"] == 1 and not report.all_counted_passed
