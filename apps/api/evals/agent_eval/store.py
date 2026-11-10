"""평가 결과를 `results/<run id>/` 에 저장한다. LLM·DB·네트워크를 쓰지 않고 파일만 쓴다.

저장 원칙
- 합성 사례만 저장한다(`meta.synthetic` 이 True 가 아니면 거부).
- 필드는 허용 목록으로 최소화한다. 사례의 질문·기대값 원문은 저장하지 않고 사례 id 로만 가리킨다.
- 모든 값은 쓰기 직전에 스크러버(`scrub.py`)를 거친다.
- 이미 있는 실행 id 는 덮어쓰지 않는다.
"""

import csv
import io
import json
import re
import shutil
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from .schema import Case, Observation
from .scoring import CaseResult
from .scrub import scrub_value

RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
STAGES = ("baseline", "loop", "other")
ANSWER_MAX = 500  # 답은 앞부분만 남긴다
MANIFEST_KEYS = (
    "run_id",
    "stage",
    "model",
    "git_commit",
    "prompt_hash",
    "split_hashes",
    "seed",
    "repeats",
)
MANIFEST_OPTIONAL = ("loop_id", "started_at")
USAGE_KEYS = frozenset(
    {
        "case_id",
        "repeat",
        "call_index",
        "model",
        "tokens_in",
        "tokens_out",
        "cost_usd",
        "cumulative_usd",
    }
)
FILES = (
    "manifest.json",
    "cases.jsonl",
    "trajectories.jsonl",
    "usage.jsonl",
    "summary.csv",
    "failures.csv",
)


class RunLike(Protocol):
    """사례 하나의 실행 묶음(예: `metrics.CaseRun`). 반복마다 채점 결과와 관찰 결과가 하나씩 있다."""

    case: Case
    results: Sequence[CaseResult]
    observations: Sequence[Observation]


def _jsonl(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(
        json.dumps(scrub_value(r), ensure_ascii=False, sort_keys=True) + "\n" for r in rows
    )


def _csv(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(scrub_value(list(r)) for r in rows)
    return out.getvalue()


def _check_manifest(manifest: Mapping[str, Any]) -> None:
    extra = set(manifest) - set(MANIFEST_KEYS) - set(MANIFEST_OPTIONAL)
    missing = [k for k in MANIFEST_KEYS if k not in manifest]
    if extra or missing:
        raise ValueError(f"manifest 키가 맞지 않는다(빠짐 {missing}, 허용 밖 {sorted(extra)})")
    if not RUN_ID.fullmatch(str(manifest["run_id"])):
        raise ValueError("run_id 는 영문·숫자·`_.-` 만, 64자 이하")
    if manifest["stage"] not in STAGES:
        raise ValueError(f"stage 는 {STAGES} 중 하나")


def _build(runs: Sequence[RunLike]) -> tuple[list[dict], list[dict], list[list]]:
    cases, trajectories, failures = [], [], []
    for run in runs:
        case = run.case
        if not isinstance(case, Case) or case.meta.synthetic is not True:
            raise ValueError("합성 표시가 없는 사례는 저장하지 않는다")
        if not run.results or len(run.results) != len(run.observations):
            raise ValueError(f"{case.id}: 채점 결과와 관찰 결과의 수가 같고 1개 이상이어야 한다")
        for repeat, (res, obs) in enumerate(zip(run.results, run.observations, strict=True)):
            cases.append(
                {
                    "case_id": case.id,
                    "split": case.split,
                    "category": case.category,
                    "scenario": case.scenario,
                    "repeat": repeat,
                    "passed": res.passed,
                    "tools_ok": res.tools_ok,
                    "calls_ok": res.calls_ok,
                    "outcome_ok": res.outcome_ok,
                    "answer_ok": res.answer_ok,
                    "security_violations": list(res.security_violations),
                    "failure_types": list(res.failure_types),
                }
            )
            trajectories.append(
                {
                    "case_id": case.id,
                    "repeat": repeat,
                    "calls": [
                        {
                            "stage": c.stage,
                            "name": c.name,
                            "args": c.args,
                            "is_error": c.is_error,
                            "superseded": c.superseded,
                        }
                        for c in obs.calls
                    ],
                    "answer": obs.answer[:ANSWER_MAX],
                    "proposals": len(obs.proposals),
                    "can_answer": obs.can_answer,
                    "posted_to_room": obs.posted_to_room,
                    "card_kind": obs.card_kind,
                    "steps": obs.steps,
                    "llm_calls": obs.llm_calls,
                    "tokens_in": obs.tokens_in,
                    "tokens_out": obs.tokens_out,
                    "latency_ms": obs.latency_ms,
                    "step_limit_hit": obs.step_limit_hit,
                }
            )
            if not res.passed:
                failures.append(
                    [
                        case.id,
                        case.split,
                        case.category,
                        case.scenario or "",
                        repeat,
                        ";".join(res.failure_types),
                        ";".join(res.security_violations),
                    ]
                )
    return cases, trajectories, failures


def write_run(
    root: Path,
    manifest: Mapping[str, Any],
    runs: Sequence[RunLike],
    usages: Sequence[Mapping[str, Any]],
    summary_rows: Sequence[tuple[str, Any]],
) -> Path:
    """실행 하나의 결과를 `root/<run_id>/` 에 쓴다. usages 는 `cost.CallUsage.as_dict()` 의 목록이다.

    manifest 에는 호출하는 쪽이 `MANIFEST_KEYS`(와 선택 키)를 넘기고, 비용 합계(`cost_usd`)·호출 수(`calls`)·
    사례 수(`cases`)는 여기서 usages 와 runs 로 계산해 넣는다.
    """
    _check_manifest(manifest)
    for u in usages:
        if set(u) != USAGE_KEYS:
            raise ValueError(f"usage 키가 맞지 않는다: {sorted(set(u) ^ USAGE_KEYS)}")
    cases, trajectories, failures = _build(runs)
    total = sum((Decimal(str(u["cost_usd"])) for u in usages), Decimal(0))
    final = {**manifest, "cost_usd": format(total, "f"), "calls": len(usages), "cases": len(runs)}
    contents = {
        "manifest.json": json.dumps(
            scrub_value(final), ensure_ascii=False, sort_keys=True, indent=2
        )
        + "\n",
        "cases.jsonl": _jsonl(cases),
        "trajectories.jsonl": _jsonl(trajectories),
        "usage.jsonl": _jsonl(list(usages)),
        "summary.csv": _csv(("metric", "value"), [list(r) for r in summary_rows]),
        "failures.csv": _csv(
            (
                "case_id",
                "split",
                "category",
                "scenario",
                "repeat",
                "failure_types",
                "security_violations",
            ),
            failures,
        ),
    }
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / str(manifest["run_id"])
    run_dir.mkdir()  # 이미 있으면 FileExistsError(덮어쓰지 않는다)
    try:
        for name, text in contents.items():
            (run_dir / name).write_text(text, encoding="utf-8", newline="")
    except OSError:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
    return run_dir


def opening_spent(root: Path, stage: str, loop_id: str | None = None) -> dict[str, Decimal]:
    """이전 실행 기록(manifest)에서 예산 범위별 지금까지의 합을 복원한다.

    키는 `cost.Scope` 의 값("project"·"baseline"·"loop")이라 `Ledger(opening=...)` 에 그대로 쓸 수 있다.
    loop 는 같은 loop_id 의 실행만 센다. 읽을 수 없는 manifest 는 합을 줄일 수 있으므로 오류로 멈춘다.
    """
    spent = {"project": Decimal(0), "baseline": Decimal(0), "loop": Decimal(0)}
    if not root.exists():
        return spent
    for path in sorted(root.glob("*/manifest.json")):
        try:
            m = json.loads(path.read_text(encoding="utf-8"))
            cost = Decimal(str(m["cost_usd"]))
            run_stage, run_loop = m["stage"], m.get("loop_id")
        except (OSError, ValueError, KeyError, ArithmeticError) as e:
            raise ValueError(f"manifest 를 읽을 수 없다: {path.parent.name}") from e
        spent["project"] += cost
        if run_stage == "baseline" and stage == "baseline":
            spent["baseline"] += cost
        if run_stage == "loop" and stage == "loop" and loop_id is not None and run_loop == loop_id:
            spent["loop"] += cost
    return spent
