"""보안 위반 즉시 중단의 **보고 지표와 경계 조건**(L0, 가짜 모델·합성 DB, 실호출 0회).

기존 `counts()`·`metrics` 입력(`report.stored`)을 바꾸지 않고, 중단된 실행에서도 예정/완료/미실행 수, 완료분의 통과·실패·Task Success, 모든 반복이 끝난 사례의 기존 metrics,
실제 보안 위반 수가 `runner_report.json`·manifest·`summary.csv` 에 맞게 나오는지 본다. 위반이 첫 실행·중간 반복·마지막 반복에 나는 경우와 승인 없는 쓰기·일반 실패·예산 중단,
CLI 의 후속 분할 차단을 확인한다. 반복마다 다른 대본은 `_Seq`(사례 id 의 대본을 호출 순서대로 돌려주는 사전)로 만든다.
"""

import json
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from evals.agent_eval import case_files as cf
from evals.agent_eval import cli, dev_cases, dev_scripts, runner, store
from evals.agent_eval.cost import Ledger, Scope
from tests.agent_eval.runner_support import run

VIOLATING = dev_scripts.VIOLATING


class _Seq(dict):
    """`scripts.get(case_id)` 를 부를 때마다(반복마다 한 번) 목록의 다음 대본을 돌려준다. 다른 사례는 평소 사전처럼 동작한다."""

    def __init__(self, base, case_id, sequence):
        super().__init__(base)
        self.case_id, self.sequence, self.n = case_id, list(sequence), 0
        self[case_id] = self.sequence[0]

    def get(self, key, default=None):
        if key == self.case_id:
            script = self.sequence[min(self.n, len(self.sequence) - 1)]
            self.n += 1
            return script
        return super().get(key, default)


@pytest.fixture(scope="module")
def cases():
    return {c.id: c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}


def _violating(prefix=None):
    for cid, variants in VIOLATING.items():
        for _name, v in variants.items():
            if prefix is None or v.label.startswith(prefix):
                return cid, v
    raise AssertionError(prefix)


def _normal_other(n=1):
    return [i for i in sorted(dev_scripts.SCRIPTS) if i not in VIOLATING][:n]


def _run(cases, tmp_path, rid, sequence_kinds, repeats, prefix=None, extra=1, **kw):
    """위반 사례(첫 번째) + 정상 사례 extra 개. sequence_kinds: 반복마다 'ok'|'bad' (위반 사례의 대본)."""
    cid, v = _violating(prefix)
    others = _normal_other(extra)
    seq = [dev_scripts.SCRIPTS[cid] if k == "ok" else v.script for k in sequence_kinds]
    scripts = _Seq({o: dev_scripts.SCRIPTS[o] for o in others}, cid, seq)
    items = [cases[i] for i in (cid, *others)]
    return (
        cid,
        others,
        run(
            items,
            tmp_path,
            run_id=rid,
            repeats=repeats,
            scripts=scripts,
            stop_on_security=True,
            **kw,
        ),
    )


def _files(report):
    d = report.run_dir
    return (
        json.loads((d / "manifest.json").read_text("utf-8")),
        json.loads((d / "runner_report.json").read_text("utf-8")),
        dict(
            line.split(",", 1) for line in (d / "summary.csv").read_text("utf-8").splitlines()[1:]
        ),
    )


def test_a_violation_in_the_first_run_still_reports_the_failure_and_the_violation(cases, tmp_path):
    """첫 실행에서 위반 → 지표 입력에 들어가는 사례가 없어도 실패·위반·미실행이 보고서에 나온다."""
    cid, others, report = _run(cases, tmp_path, "b-first", ["bad"], repeats=3)
    m, rr, s = _files(report)
    assert report.stored == [] and [p.case.id for p in report.partial] == [cid]
    # 예정 6 = 사례 2 x 반복 3, 완료 1, 미실행 5
    assert (m["runs_planned"], m["runs_completed"], m["runs_not_started"]) == (6, 1, 5)
    assert m["halt_case_id"] == cid and m["halt_repeat"] == 0 and m["cases"] == 0
    c = rr["counts"]
    assert (c["iterations"], c["judged"], c["passed"], c["failed"]) == (1, 1, 0, 1)
    assert s["runner.failed"] == "1" and s["runner.passed"] == "0" and s["runner.judged"] == "1"
    assert s["runner.security_halted"] == "1" and s["runner.runs_not_started"] == "5"
    assert not any(k.startswith("metrics.") for k in s)  # 기존 metrics 입력이 없다
    assert [r["case_id"] for r in rr["cases"] if r["security_violations"]] == [cid]
    assert rr["security_halt"]["violations"] and rr["security_halt"]["runs_completed"] == 1
    assert (report.run_dir / store.PARTIAL_FILE).is_file()
    assert not (report.run_dir / "cases.jsonl").read_text("utf-8").strip()  # 지표 행 없음


def test_a_violation_in_a_middle_repeat_keeps_the_earlier_passes_as_completed_results(
    cases, tmp_path
):
    cid, others, report = _run(cases, tmp_path, "b-mid", ["ok", "bad", "ok"], repeats=3)
    m, rr, s = _files(report)
    assert (m["runs_planned"], m["runs_completed"], m["runs_not_started"]) == (6, 2, 4)
    assert m["halt_repeat"] == 1
    c = rr["counts"]
    assert (c["iterations"], c["passed"], c["failed"]) == (2, 1, 1)  # 완료 2: 통과 1 + 실패 1
    assert s["runner.passed"] == "1" and s["runner.failed"] == "1"
    assert report.stored == [] and len(report.partial[0].results) == 2  # 반복이 남아 부분 결과
    rows = [
        json.loads(x) for x in (report.run_dir / store.PARTIAL_FILE).read_text("utf-8").splitlines()
    ]
    assert [(r["row"]["repeat"], r["row"]["passed"]) for r in rows] == [(0, True), (1, False)]
    assert not any(k.startswith("metrics.") for k in s)


def test_a_violation_in_the_last_repeat_keeps_the_case_in_the_existing_metrics(cases, tmp_path):
    cid, others, report = _run(cases, tmp_path, "b-last", ["ok", "ok", "bad"], repeats=3)
    m, rr, s = _files(report)
    assert (m["runs_planned"], m["runs_completed"], m["runs_not_started"]) == (6, 3, 3)
    assert [x.case.id for x in report.stored] == [cid] and report.partial == []
    assert (
        m["cases"] == 1 and s["metrics.runs"] == "3"
    )  # 모든 반복이 끝난 사례는 기존 metrics 에 그대로
    c = rr["counts"]
    assert (c["passed"], c["failed"]) == (2, 1)
    assert [r["repeat"] for r in rr["cases"] if r["security_violations"]] == [2]
    assert not (report.run_dir / store.PARTIAL_FILE).exists()  # 부분 결과가 없다
    # 미실행 사례는 어느 집계에도 없다
    assert all(r["case_id"] == cid for r in rr["cases"])


def test_an_unapproved_write_violation_is_counted_and_stops_the_run(cases, tmp_path):
    cid, others, report = _run(cases, tmp_path, "b-write", ["bad"], repeats=2, prefix="write:")
    m, rr, s = _files(report)
    assert (
        rr["counts"]["security_write_attempts"] == 1 and s["runner.security_write_attempts"] == "1"
    )
    assert any(v.startswith("write:") for v in m["security_violations"])
    assert (m["runs_completed"], m["runs_not_started"]) == (1, 3)


def test_an_ordinary_failure_is_not_a_halt_and_stays_in_the_counts(cases, tmp_path):
    a, b = _normal_other(2)
    scripts = {
        a: dev_scripts.SCRIPTS[b],
        b: dev_scripts.SCRIPTS[b],
    }  # a 는 다른 사례의 대본이라 실패
    report = run(
        [cases[a], cases[b]],
        tmp_path,
        run_id="b-ord",
        repeats=2,
        scripts=scripts,
        stop_on_security=True,
    )
    m, rr, s = _files(report)
    assert report.security_halt is None and "security_halt" not in rr and "halt_kind" not in m
    assert rr["counts"]["iterations"] == 4 and rr["counts"]["failed"] >= 1
    assert "runner.security_halted" not in s


def test_a_budget_halt_is_not_reported_as_a_security_halt(cases, tmp_path):
    a, b = _normal_other(2)
    tiny = Ledger((Scope.RUN,), caps={Scope.RUN: D("0.0001")})
    report = run(
        [cases[a], cases[b]],
        tmp_path,
        run_id="b-budget",
        scripts={i: dev_scripts.SCRIPTS[i] for i in (a, b)},
        ledger=tiny,
        stop_on_security=True,
    )
    rr = json.loads((report.run_dir / "runner_report.json").read_text("utf-8"))
    assert report.halted and report.security_halt is None
    assert rr["counts"]["halted"] == 1 and "security_halt" not in rr
    # 첫 호출 전에 멈춰 지출이 없으면 기존처럼 manifest·summary 를 쓰지 않는다(기존 동작 그대로)
    assert not (report.run_dir / "manifest.json").exists()


def test_the_completed_task_success_can_be_read_from_the_existing_counts(cases, tmp_path):
    """완료 실행 기준 Task Success = counts 의 passed / judged. 미실행은 분모에 없다(예: 완료 2, 통과 1 → 1/2)."""
    cid, others, report = _run(cases, tmp_path, "b-ts", ["ok", "bad", "ok"], repeats=3)
    _, rr, _ = _files(report)
    c = rr["counts"]
    assert c["judged"] == 2 and c["passed"] / c["judged"] == 0.5
    assert rr["security_halt"]["runs_not_started"] == 4  # 미실행 4건은 통과도 실패도 아니다


def test_a_security_halt_in_one_split_stops_the_remaining_splits(tmp_path, monkeypatch):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-secret")
    monkeypatch.setattr(cli, "_load", lambda *a, **k: [])
    seen = []

    def fake_run(source, options, ledger=None, **_):
        seen.append(options.run_id)
        ledger.total = D("0.1")
        return SimpleNamespace(
            ledger=ledger,
            run_dir=None,
            halted=None,
            security_halt={"case_id": "x", "repeat": 0, "violations": ["common[1]"], "planned": 3},
            all_counted_passed=False,
            summary_lines=lambda: [],
        )

    monkeypatch.setattr(runner, "run_cases", fake_run)
    plan = cli.Plan("fake", ("legacy", "dev", "val"), None, "r", 1, ())
    args = cli.build_parser().parse_args(["--results-dir", str(tmp_path / "results")])
    code = cli._execute(args, plan, lambda _: None)
    assert (
        code == cli.HALTED and len(seen) == 1
    )  # 첫 분할의 보안 중단 뒤 남은 분할은 실행하지 않는다
