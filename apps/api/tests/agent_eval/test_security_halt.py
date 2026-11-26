"""보안 위반 즉시 중단(L0, 가짜 모델·합성 DB, 실제 호출 0회): case-run 이 끝나고 기존 보안 판정에 위반이 있으면 후속 case-run 을 시작하지 않는다.

보장 범위는 **후속 case-run 차단**이다(위반이 난 요청 안에서 이미 나간 호출은 막지 못한다). 판정·채점기·정답지·비용 게이트는 그대로고 이미 계산된 `security_violations` 만 쓴다.
"""

import json
from decimal import Decimal as D

import pytest

from evals.agent_eval import case_files as cf
from evals.agent_eval import dev_cases, dev_scripts, store
from evals.agent_eval.cost import Ledger, Scope
from tests.agent_eval.runner_support import run

VIOLATING = dev_scripts.VIOLATING


@pytest.fixture(scope="module")
def cases():
    return {c.id: c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}


def _normal_ids(n):
    ids = [i for i in sorted(dev_scripts.SCRIPTS) if i not in VIOLATING]
    return ids[:n]


def _violating(prefix=None):
    for cid, variants in VIOLATING.items():
        for name, v in variants.items():
            if prefix is None or v.label.startswith(prefix):
                return cid, name, v
    raise AssertionError(f"위반 대본이 없다: {prefix}")


def _scripts(cases_ids, violating=None):
    scripts = {i: dev_scripts.SCRIPTS[i] for i in cases_ids}
    if violating:
        cid, _, v = violating
        scripts[cid] = v.script
    return scripts


def _plan(cases, violating, repeats=2):
    a, b, c = _normal_ids(3)
    cid = violating[0]
    order = [a, cid, b, c]  # 위반 사례는 둘째
    return order, [cases[i] for i in order], _scripts([a, b, c], violating)


def _usage_case_ids(report):
    return {u.case_id for u in report.ledger.usages}


def test_a_violation_stops_every_later_case_run_and_keeps_the_results_up_to_it(cases, tmp_path):
    violating = _violating()
    order, items, scripts = _plan(cases, violating)
    report = run(
        items, tmp_path, run_id="halt-sec", repeats=2, scripts=scripts, stop_on_security=True
    )
    a, cid, b, c = order
    done = [(r.case_id, r.repeat) for r in report.records]
    assert done == [(a, 0), (a, 1), (cid, 0)]  # 위반이 난 case-run 까지만 실행했다
    assert report.records[-1].security_violations and report.records[-1].passed is False
    # 위반 이후 추가 모델 호출 0회: 뒤 사례의 가짜 모델·사용 기록이 없다
    assert (b, 0) not in report.fakes and (c, 0) not in report.fakes
    assert _usage_case_ids(report) <= {a, cid} and not (_usage_case_ids(report) & {b, c})
    assert sum(r.llm_calls for r in report.records) == len(report.ledger.usages)
    assert report.halted is None  # 예산 중단과 별개
    assert report.halt_counts() == {"planned": 8, "completed": 3, "not_started": 5}
    assert not report.all_counted_passed
    # 끝난 사례는 저장, 위반 사례는 반복이 남아 부분 결과로 따로 보존한다(미실행은 통과도 실패도 아니다)
    assert [s.case.id for s in report.stored] == [a]
    assert [s.case.id for s in report.partial] == [cid] and len(report.partial[0].results) == 1


def test_the_manifest_report_and_partial_file_record_the_halt(cases, tmp_path):
    violating = _violating()
    order, items, scripts = _plan(cases, violating)
    report = run(
        items, tmp_path, run_id="halt-sec", repeats=2, scripts=scripts, stop_on_security=True
    )
    d = report.run_dir
    m = json.loads((d / "manifest.json").read_text("utf-8"))
    assert m["halt_kind"] == "security" and m["halt_case_id"] == order[1] and m["halt_repeat"] == 0
    assert (m["runs_planned"], m["runs_completed"], m["runs_not_started"]) == (8, 3, 5)
    assert m["security_violations"] and m["cost_usd"] == format(report.ledger.total, "f")
    assert m["cases"] == 1  # 지표 대상(끝난 사례)은 하나
    rr = json.loads((d / "runner_report.json").read_text("utf-8"))
    sh = rr["security_halt"]
    assert sh["halted"] is True and sh["runs_not_started"] == 5 and sh["violations"]
    assert rr["counts"]["iterations"] == 3  # 미실행은 반복 기록에 없다(통과·실패로 세지 않는다)
    rows = [json.loads(x) for x in (d / "cases.jsonl").read_text("utf-8").splitlines()]
    assert {r["case_id"] for r in rows} == {order[0]}  # 지표 입력에는 끝난 사례만
    partial = [json.loads(x) for x in (d / store.PARTIAL_FILE).read_text("utf-8").splitlines()]
    assert [(p["row"]["case_id"], p["row"]["repeat"]) for p in partial] == [(order[1], 0)]
    assert (
        partial[0]["row"]["security_violations"] and partial[0]["trajectory"]["calls"] is not None
    )
    summary = dict(
        line.split(",", 1) for line in (d / "summary.csv").read_text("utf-8").splitlines()[1:]
    )
    assert summary["runner.security_halted"] == "1" and summary["runner.runs_not_started"] == "5"
    assert (
        int(summary["metrics.runs"]) == 2
    )  # 지표는 끝난 사례 A 의 두 반복만(위반 사례·미실행은 분모에 없다)


def test_an_unapproved_write_attempt_also_stops_the_run(cases, tmp_path):
    violating = _violating("write:")
    order, items, scripts = _plan(cases, violating)
    report = run(
        items, tmp_path, run_id="halt-write", repeats=1, scripts=scripts, stop_on_security=True
    )
    assert [r.case_id for r in report.records][-1] == order[1] and len(report.records) == 2
    assert any(v.startswith("write:") for v in report.records[-1].security_violations)
    assert report.security_halt and report.halt_counts()["not_started"] == 2


def test_an_ordinary_task_success_failure_does_not_stop_the_run(cases, tmp_path):
    a, b, c = _normal_ids(3)
    scripts = {a: dev_scripts.SCRIPTS[b], b: dev_scripts.SCRIPTS[b], c: dev_scripts.SCRIPTS[c]}
    report = run(
        [cases[a], cases[b], cases[c]],
        tmp_path,
        run_id="halt-none",
        repeats=2,
        scripts=scripts,
        stop_on_security=True,
    )
    assert len(report.records) == 6 and report.security_halt is None
    assert not any(r.security_violations for r in report.records)
    assert report.counts()["failed"] >= 1  # 일반 실패는 평가 결과로 남고 후속 실행을 막지 않는다
    m = json.loads((report.run_dir / "manifest.json").read_text("utf-8"))
    assert not any(k in m for k in store.HALT_KEYS)
    assert not (report.run_dir / store.PARTIAL_FILE).exists()


def test_without_the_option_the_run_continues_exactly_as_before(cases, tmp_path):
    violating = _violating()
    order, items, scripts = _plan(cases, violating)
    report = run(items, tmp_path, run_id="halt-off", repeats=2, scripts=scripts)  # 기본 False
    assert len(report.records) == 8 and report.security_halt is None and report.partial == []
    m = json.loads((report.run_dir / "manifest.json").read_text("utf-8"))
    assert not any(k in m for k in store.HALT_KEYS)
    assert "security_halt" not in json.loads(
        (report.run_dir / "runner_report.json").read_text("utf-8")
    )
    assert not (report.run_dir / store.PARTIAL_FILE).exists()


def test_a_clean_run_has_the_same_files_with_and_without_the_option(cases, tmp_path):
    ids = _normal_ids(2)
    scripts = _scripts(ids)
    on = run(
        [cases[i] for i in ids], tmp_path, run_id="clean-on", scripts=scripts, stop_on_security=True
    )
    off = run([cases[i] for i in ids], tmp_path, run_id="clean-off", scripts=scripts)
    assert sorted(p.name for p in on.run_dir.iterdir()) == sorted(
        p.name for p in off.run_dir.iterdir()
    )
    assert on.counts() == off.counts() and on.all_counted_passed and off.all_counted_passed
    assert (on.run_dir / "summary.csv").read_text("utf-8").count("security_halted") == 0


def test_a_budget_halt_still_works_and_is_not_a_security_halt(cases, tmp_path):
    ids = _normal_ids(2)
    tiny = Ledger((Scope.RUN,), caps={Scope.RUN: D("0.0001")})
    report = run(
        [cases[i] for i in ids],
        tmp_path,
        run_id="halt-budget",
        scripts=_scripts(ids),
        ledger=tiny,
        stop_on_security=True,
    )
    assert report.halted and "호출 전에 멈춘다" in report.halted
    assert report.security_halt is None and [r.status for r in report.records] == ["halted"]


def test_the_manifest_halt_keys_are_all_or_nothing_and_checked(tmp_path):
    base = dict(
        run_id="m-1", stage="other", model="claude-haiku-5-5", git_commit="a" * 7,
        prompt_hash="b" * 7, split_hashes={"dev": "c" * 7}, seed=0, repeats=1,
    )  # fmt: skip
    good = dict(
        halt_kind="security", halt_reason="보안 위반", halt_case_id="s-dev-1", halt_repeat=0,
        runs_planned=4, runs_completed=1, runs_not_started=3, security_violations=["common[1]"],
    )  # fmt: skip
    store._check_manifest({**base, **good})
    with pytest.raises(ValueError):
        store._check_manifest({**base, **{k: v for k, v in good.items() if k != "halt_repeat"}})
    with pytest.raises(ValueError):
        store._check_manifest({**base, **good, "runs_not_started": 2})  # 합이 예정과 다르다
    with pytest.raises(ValueError):
        store._check_manifest({**base, **good, "security_violations": []})
    with pytest.raises(ValueError):
        store._check_manifest({**base, **good, "halt_kind": "budget"})


def test_only_the_real_mode_cli_turns_the_option_on():
    import inspect

    from evals.agent_eval import cli, runner

    assert runner.RunOptions(run_id="x").stop_on_security is False
    source = inspect.getsource(cli._execute)
    assert (
        'stop_on_security = mode == "real"' in source
        and "stop_on_security=stop_on_security" in source
    )
