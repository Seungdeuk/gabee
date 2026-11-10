"""결과 저장 시험(L0). 임시 폴더에 파일만 쓰고 LLM·DB 는 쓰지 않는다."""

import csv
import json
from dataclasses import dataclass
from decimal import Decimal as D

import pytest

from evals.agent_eval.schema import Case, Observation, Security, ToolCall
from evals.agent_eval.scoring import CaseResult, score_case
from evals.agent_eval.store import ANSWER_MAX, FILES, opening_spent, write_run

QUESTION = "내일 3시 치과 등록해줘 (질문 원문)"
USAGE = {
    "case_id": "a",
    "repeat": 0,
    "call_index": 0,
    "model": "claude-haiku-5-5",
    "tokens_in": 1000,
    "tokens_out": 500,
    "cost_usd": "0.00035",
    "cumulative_usd": "0.00035",
}


@dataclass
class Run:
    case: Case
    results: tuple[CaseResult, ...]
    observations: tuple[Observation, ...]


def _case(cid="a", expect=None):
    return Case.model_validate(
        {
            "id": cid,
            "split": "dev",
            "category": "C",
            "scenario": "single_tool",
            "agent_path": "schedule",
            "question": QUESTION,
            "expect": expect or {"tools": {"required": ["register"]}},
            "meta": {"synthetic": True},
        }
    )


def _run(case, *observations):
    return Run(
        case, tuple(score_case(case, o, Security()) for o in observations), tuple(observations)
    )


def _manifest(run_id="r1", stage="baseline", **extra):
    base = {
        "run_id": run_id,
        "stage": stage,
        "model": "claude-haiku-5-5",
        "git_commit": "abc1234",
        "prompt_hash": "p1",
        "split_hashes": {"dev": "h1"},
        "seed": 7,
        "repeats": 2,
    }
    return {**base, **extra}


GOOD = Observation(
    calls=[ToolCall(stage="schedule", name="register", args={"title": "치과"})], can_answer=True
)
LEAKY = Observation(
    answer="전화는 010-1234-5678 입니다 " + "가" * 600,
    calls=[ToolCall(stage="schedule", name="x", args={"to": "a@b.com"})],
)


def _write(tmp_path, **kw):
    runs = kw.pop("runs", [_run(_case(), GOOD, LEAKY)])
    usages = kw.pop("usages", [USAGE])
    return write_run(
        tmp_path,
        kw.pop("manifest", _manifest()),
        runs,
        usages,
        kw.pop("rows", [("pass_at_all", 0.5)]),
    )


def test_write_run_creates_exactly_the_agreed_files_with_computed_totals(tmp_path):
    run_dir = _write(
        tmp_path,
        usages=[
            USAGE,
            {**USAGE, "call_index": 1, "cost_usd": "0.00065", "cumulative_usd": "0.001"},
        ],
    )
    assert sorted(p.name for p in run_dir.iterdir()) == sorted(FILES)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cost_usd"] == "0.00100" and manifest["calls"] == 2 and manifest["cases"] == 1
    assert manifest["split_hashes"] == {"dev": "h1"}
    rows = [
        json.loads(line)
        for line in (run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [(r["repeat"], r["passed"]) for r in rows] == [(0, True), (1, False)]
    assert set(rows[0]) == {
        "case_id", "split", "category", "scenario", "repeat", "passed", "tools_ok", "calls_ok",
        "outcome_ok", "answer_ok", "security_violations", "failure_types",
    }  # fmt: skip
    summary = list(csv.reader((run_dir / "summary.csv").read_text(encoding="utf-8").splitlines()))
    assert summary == [["metric", "value"], ["pass_at_all", "0.5"]]


def test_only_failed_runs_go_to_failures_csv(tmp_path):
    run_dir = _write(tmp_path)
    rows = list(csv.reader((run_dir / "failures.csv").read_text(encoding="utf-8").splitlines()))
    assert rows[0][0] == "case_id" and len(rows) == 2
    assert rows[1][:5] == ["a", "dev", "C", "single_tool", "1"] and rows[1][5] == "missing_tool"


def test_files_hold_no_question_text_and_no_unscrubbed_personal_data(tmp_path):
    run_dir = _write(tmp_path)
    everything = "".join((run_dir / name).read_text(encoding="utf-8") for name in FILES)
    assert QUESTION not in everything and "질문 원문" not in everything
    assert "010-1234-5678" not in everything and "a@b.com" not in everything
    assert "[전화번호]" in everything and "[이메일]" in everything


def test_answers_are_truncated_and_trajectories_keep_only_the_allowed_fields(tmp_path):
    run_dir = _write(tmp_path)
    rows = [
        json.loads(line)
        for line in (run_dir / "trajectories.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows[1]["answer"]) <= ANSWER_MAX + len("[전화번호]")
    assert set(rows[0]) == {
        "case_id", "repeat", "calls", "answer", "proposals", "can_answer", "posted_to_room", "card_kind",
        "steps", "llm_calls", "tokens_in", "tokens_out", "latency_ms", "step_limit_hit",
    }  # fmt: skip
    assert set(rows[0]["calls"][0]) == {"stage", "name", "args", "is_error", "superseded"}


def test_non_synthetic_cases_are_refused_and_nothing_is_written(tmp_path):
    bad = _case().model_copy(update={"meta": _case().meta.model_copy(update={"synthetic": False})})
    with pytest.raises(ValueError):
        _write(tmp_path, runs=[_run(bad, GOOD)])
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize(
    "manifest",
    [
        _manifest(run_id="../escape"),
        _manifest(run_id=""),
        _manifest(run_id="a/b"),
        _manifest(stage="final"),
        {**_manifest(), "note": "free text"},  # 허용 밖 키
        {k: v for k, v in _manifest().items() if k != "model"},
    ],
)
def test_bad_manifests_are_refused(tmp_path, manifest):
    with pytest.raises(ValueError):
        _write(tmp_path, manifest=manifest)
    assert not any(tmp_path.iterdir())


def test_usage_rows_with_unexpected_keys_are_refused(tmp_path):
    with pytest.raises(ValueError):
        _write(tmp_path, usages=[{**USAGE, "answer": "내용"}])
    with pytest.raises(ValueError):
        _write(tmp_path, usages=[{k: v for k, v in USAGE.items() if k != "model"}])


def test_an_existing_run_is_never_overwritten(tmp_path):
    run_dir = _write(tmp_path)
    before = (run_dir / "cases.jsonl").read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        _write(tmp_path, runs=[_run(_case("zzz"), GOOD)])
    assert (run_dir / "cases.jsonl").read_text(encoding="utf-8") == before


def test_runs_with_mismatched_results_are_refused(tmp_path):
    run = _run(_case(), GOOD)
    with pytest.raises(ValueError):
        _write(tmp_path, runs=[Run(run.case, run.results, (GOOD, GOOD))])
    with pytest.raises(ValueError):
        _write(tmp_path, runs=[Run(run.case, (), ())])


def test_opening_spent_restores_scope_totals_from_manifests(tmp_path):
    cost = lambda c: [{**USAGE, "cost_usd": c, "cumulative_usd": c}]  # noqa: E731
    _write(tmp_path, manifest=_manifest("b1", "baseline"), usages=cost("1.5"))
    _write(tmp_path, manifest=_manifest("b2", "baseline"), usages=cost("0.25"))
    _write(tmp_path, manifest=_manifest("l1", "loop", loop_id="L1"), usages=cost("2"))
    _write(tmp_path, manifest=_manifest("l2", "loop", loop_id="L2"), usages=cost("3"))
    _write(tmp_path, manifest=_manifest("o1", "other"), usages=cost("0.5"))
    assert opening_spent(tmp_path, "baseline") == {
        "project": D("7.25"),
        "baseline": D("1.75"),
        "loop": 0,
    }
    assert opening_spent(tmp_path, "loop", "L1") == {
        "project": D("7.25"),
        "baseline": 0,
        "loop": D("2"),
    }
    assert opening_spent(tmp_path, "loop", "L9")["loop"] == 0
    assert opening_spent(tmp_path, "loop")["loop"] == 0  # loop_id 없이는 루프 합을 세지 않는다


def test_opening_spent_is_zero_for_a_missing_folder_and_stops_on_a_broken_manifest(tmp_path):
    assert opening_spent(tmp_path / "none", "baseline") == {"project": 0, "baseline": 0, "loop": 0}
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        opening_spent(tmp_path, "baseline")


def test_summary_csv_values_are_scrubbed_too(tmp_path):
    run_dir = _write(tmp_path, rows=[("note", "연락처 010-1234-5678"), ("pass_at_all", 0.5)])
    text = (run_dir / "summary.csv").read_text(encoding="utf-8")
    assert "010-1234-5678" not in text and "[전화번호]" in text
