"""평가 결과를 `results/<run id>/` 에 저장한다. LLM·DB·네트워크를 쓰지 않고 파일만 쓴다.

저장 원칙
- 합성 사례만 저장한다(`meta.synthetic` 이 True 가 아니면 거부).
- 필드는 허용 목록으로 최소화하고 값 형식도 검사한다. 사례의 질문·기대값 원문은 저장하지 않고 사례 id 로만
  가리킨다. 도구 인자는 스크러버를 거치고 문자열 값을 `ARG_VALUE_MAX` 자로 자른다.
- 모든 값은 쓰기 직전에 스크러버(`scrub.py`)를 거친다. 답은 지운 다음에 자른다(번호가 반쪽만 남지 않게).
- 이미 있는 실행 id 는 덮어쓰지 않고, 임시 폴더에 다 쓴 뒤 옮겨서 반쯤 쓰다 만 결과가 남지 않게 한다.
- 루프에서 후보를 만든 호출의 사용량도 같은 `loop_id` 의 실행 기록(`usages`)에 넣어야 재시작 뒤에도 합이 맞는다.
"""

import csv
import io
import json
import re
import shutil
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

from .schema import Case, Observation
from .scoring import CaseResult
from .scrub import scrub_text, scrub_value

RUN_ID = re.compile(r"[a-z0-9](?:[a-z0-9_.-]{0,62}[a-z0-9])?")  # 소문자만, 끝은 영숫자
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
_HEX = re.compile(r"[0-9a-f]{7,64}")
_STARTED_AT = re.compile(r"\d{4}-\d{2}-\d{2}T[0-9:.+Z-]{1,40}")
_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
STAGES = ("baseline", "loop", "other")
ANSWER_MAX = 500  # 답은 앞부분만 남긴다
ARG_VALUE_MAX = 200  # 도구 인자의 문자열 값
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
RESCORE_KEYS = (
    "rescored_from",
    "source_git_commit",
    "scorer_version",
    "cases_hash",
    "rescore_label",
)  # 소급 재채점 결과(`rescore.py`)에만 쓴다. 다섯 개가 모두 있거나 모두 없어야 한다
MANIFEST_OPTIONAL = (
    "loop_id",
    "started_at",
    *RESCORE_KEYS,
)  # loop_id 는 stage 가 loop 일 때만(그리고 반드시) 둔다
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


def _is_int(value: Any, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _money(value: Any) -> Decimal:
    """비용 값은 유한하고 0 이상인 숫자여야 한다(음수·NaN 은 합을 줄이거나 망가뜨린다)."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"비용 값이 숫자가 아니다: {value!r}") from e
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"비용은 0 이상의 유한한 수여야 한다: {value!r}")
    return amount


def _cap(value: Any) -> Any:
    if isinstance(value, str):
        return value[:ARG_VALUE_MAX]
    if isinstance(value, dict):
        return {k: _cap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cap(v) for v in value]
    return value


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
    run_id = manifest["run_id"]
    if (
        not isinstance(run_id, str)
        or not RUN_ID.fullmatch(run_id)
        or run_id.split(".")[0] in _RESERVED
    ):
        raise ValueError("run_id 는 소문자·숫자·`_.-` 만, 64자 이하, 끝은 영숫자, 장치 이름 불가")
    if manifest["stage"] not in STAGES:
        raise ValueError(f"stage 는 {STAGES} 중 하나")
    present = [k for k in RESCORE_KEYS if k in manifest]
    if present and len(present) != len(RESCORE_KEYS):
        raise ValueError(f"재채점 키는 모두 있거나 모두 없어야 한다(있는 것: {present})")
    if (
        present and manifest["stage"] != "other"
    ):  # 재채점 결과가 baseline·loop 실행인 척하지 못하게 한다
        raise ValueError("재채점 결과의 stage 는 other 여야 한다")
    if present and not (
        isinstance(manifest["rescored_from"], str)
        and RUN_ID.fullmatch(manifest["rescored_from"])
        and isinstance(manifest["source_git_commit"], str)
        and _HEX.fullmatch(manifest["source_git_commit"])
        and _is_int(manifest["scorer_version"], 1)
        and isinstance(manifest["cases_hash"], str)
        and _HEX.fullmatch(manifest["cases_hash"])
        and isinstance(manifest["rescore_label"], str)
        and _NAME.fullmatch(manifest["rescore_label"])
    ):
        raise ValueError("재채점 키의 값 형식이 맞지 않는다")
    loop_id = manifest.get("loop_id")
    if (manifest["stage"] == "loop") != (loop_id is not None):
        raise ValueError("loop_id 는 stage 가 loop 일 때만, 그리고 반드시 있어야 한다")
    if loop_id is not None and not (isinstance(loop_id, str) and RUN_ID.fullmatch(loop_id)):
        raise ValueError("loop_id 형식이 맞지 않는다")
    checks = {
        "model": isinstance(manifest["model"], str) and _NAME.fullmatch(manifest["model"]),
        "git_commit": isinstance(manifest["git_commit"], str)
        and _HEX.fullmatch(manifest["git_commit"]),
        "prompt_hash": isinstance(manifest["prompt_hash"], str)
        and _HEX.fullmatch(manifest["prompt_hash"]),
        "seed": _is_int(manifest["seed"], -(2**63)),
        "repeats": _is_int(manifest["repeats"], 1),
        "started_at": "started_at" not in manifest
        or (
            isinstance(manifest["started_at"], str)
            and _STARTED_AT.fullmatch(manifest["started_at"])
        ),
        "split_hashes": isinstance(manifest["split_hashes"], dict)
        and bool(manifest["split_hashes"])
        and all(
            isinstance(k, str) and _NAME.fullmatch(k) and isinstance(v, str) and _HEX.fullmatch(v)
            for k, v in manifest["split_hashes"].items()
        ),
    }
    bad = [k for k, ok in checks.items() if not ok]
    if bad:
        raise ValueError(f"manifest 값 형식이 맞지 않는다: {bad}")


def _check_usage(u: Mapping[str, Any]) -> Decimal:
    if set(u) != USAGE_KEYS:
        raise ValueError(f"usage 키가 맞지 않는다: {sorted(set(u) ^ USAGE_KEYS)}")
    text_ok = all(isinstance(u[k], str) and _NAME.fullmatch(u[k]) for k in ("case_id", "model"))
    int_ok = all(_is_int(u[k]) for k in ("repeat", "call_index", "tokens_in", "tokens_out"))
    if not (text_ok and int_ok):
        raise ValueError("usage 값 형식이 맞지 않는다")
    _money(u["cumulative_usd"])
    return _money(u["cost_usd"])


def _check_summary(rows: Sequence[tuple[str, Any]]) -> None:
    for name, value in rows:
        number = isinstance(value, int | float) and not isinstance(value, bool)
        finite = number and (
            not isinstance(value, float) or value == value and abs(value) != float("inf")
        )
        if not (isinstance(name, str) and _NAME.fullmatch(name)) or not (value is None or finite):
            raise ValueError(f"summary 행은 (이름, 숫자 또는 None)이어야 한다: {name!r}")


ROW_EXTRA_KEYS = (
    "write_gate",
    "skipped_checks",
    "faults_injected",
)  # faults_injected: 주입 명세가 있는 사례만(선택)
WRITE_GATES = ("applied", "not_evaluated")
RowExtras = Mapping[tuple[str, int], Mapping[str, Any]]


def _check_row_extras(extras: RowExtras) -> None:
    """cases.jsonl 의 행에 덧붙일 값(쓰기 게이트 적용 여부). 형식이 다르면 아무것도 쓰지 않는다."""
    for key, extra in extras.items():
        if not (
            isinstance(key, tuple) and len(key) == 2 and isinstance(key[0], str) and _is_int(key[1])
        ):
            raise ValueError(f"row_extras 키는 (case_id, repeat) 여야 한다: {key!r}")
        unknown = sorted(set(extra) - set(ROW_EXTRA_KEYS))
        if unknown:
            raise ValueError(f"row_extras 에 허용하지 않은 키: {unknown}")
        if extra.get("write_gate") not in WRITE_GATES:
            raise ValueError(f"write_gate 는 {WRITE_GATES} 중 하나: {extra.get('write_gate')!r}")
        skipped = extra.get("skipped_checks", ())
        if not isinstance(skipped, list | tuple) or not all(isinstance(x, str) for x in skipped):
            raise ValueError("skipped_checks 는 문자열 목록이어야 한다")
        if extra["write_gate"] == "applied" and skipped:
            raise ValueError("write_gate 가 applied 면 생략한 검사가 없어야 한다")
        injected = extra.get("faults_injected")
        if injected is not None and not _is_int(injected):
            raise ValueError("faults_injected 는 0 이상의 정수여야 한다")


def _build(
    runs: Sequence[RunLike], extras: RowExtras | None = None
) -> tuple[list[dict], list[dict], list[list]]:
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
            extra = (extras or {}).get((case.id, repeat))
            if extra is not None:
                cases[-1]["write_gate"] = extra["write_gate"]
                cases[-1]["skipped_checks"] = list(extra.get("skipped_checks", ()))
                if extra.get("faults_injected") is not None:
                    cases[-1]["faults_injected"] = int(extra["faults_injected"])
            trajectories.append(
                {
                    "case_id": case.id,
                    "repeat": repeat,
                    "calls": [
                        {
                            "stage": c.stage,
                            "name": c.name,
                            "args": _cap(scrub_value(c.args)),
                            "is_error": c.is_error,
                            "superseded": c.superseded,
                        }
                        for c in obs.calls
                    ],
                    "answer": scrub_text(obs.answer)[:ANSWER_MAX],  # 지운 다음에 자른다
                    "proposals": len(obs.proposals),
                    "can_answer": obs.can_answer,
                    "posted_to_room": obs.posted_to_room,
                    "card_kind": obs.card_kind,
                    "steps": obs.steps,
                    "llm_calls": obs.llm_calls,
                    "tokens_in": obs.tokens_in,
                    "tokens_out": obs.tokens_out,
                    "latency_ms": obs.latency_ms,
                    "step_limit_reached": obs.step_limit_reached,
                    "forced_final": obs.forced_final,
                    "faults_injected": obs.faults_injected,
                    "fault_tools": list(obs.fault_tools),
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
    row_extras: RowExtras | None = None,
) -> Path:
    """실행 하나의 결과를 `root/<run_id>/` 에 쓴다. usages 는 `cost.CallUsage.as_dict()` 의 목록이다.

    manifest 에는 호출하는 쪽이 `MANIFEST_KEYS`(와 선택 키)를 넘기고, 비용 합계(`cost_usd`)·호출 수(`calls`)·
    사례 수(`cases`)는 여기서 usages 와 runs 로 계산해 넣는다. 값이 형식에 맞지 않으면 아무것도 쓰지 않는다.
    """
    _check_manifest(manifest)
    total = sum((_check_usage(u) for u in usages), Decimal(0))
    _check_summary(summary_rows)
    if row_extras:
        _check_row_extras(row_extras)
        rows = {(r.case.id, i) for r in runs for i in range(len(r.results))}
        stray = sorted(set(row_extras) - rows)
        if stray:
            raise ValueError(f"row_extras 가 저장하지 않는 행을 가리킨다: {stray[:3]}")
    cases, trajectories, failures = _build(runs, row_extras)
    final = {**manifest, "cost_usd": format(total, "f"), "calls": len(usages), "cases": len(runs)}
    contents = {
        "manifest.json": json.dumps(final, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
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
    tmp = root / f".tmp-{manifest['run_id']}-{uuid.uuid4().hex[:8]}"
    tmp.mkdir()
    try:
        for name, text in contents.items():
            (tmp / name).write_text(text, encoding="utf-8", newline="")
        if run_dir.exists():
            raise FileExistsError(f"이미 있는 실행 id 다(덮어쓰지 않는다): {run_dir.name}")
        tmp.rename(run_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return run_dir


def opening_spent(root: Path, stage: str, loop_id: str | None = None) -> dict[str, Decimal]:
    """이전 실행 기록(manifest)에서 예산 범위별 지금까지의 합을 복원한다.

    키는 `cost.Scope` 의 값("project"·"baseline"·"loop")이라 `Ledger(opening=...)` 에 그대로 쓸 수 있다.
    stage 가 loop 면 loop_id 가 필요하고, 같은 loop_id 의 실행만 loop 합에 센다. 읽을 수 없거나 값이 이상한
    manifest 는 합을 줄일 수 있으므로 오류로 멈춘다.
    """
    if stage not in STAGES:
        raise ValueError(f"stage 는 {STAGES} 중 하나")
    if (stage == "loop") != (loop_id is not None):
        raise ValueError("loop_id 는 stage 가 loop 일 때만, 그리고 반드시 필요하다")
    spent = {"project": Decimal(0), "baseline": Decimal(0), "loop": Decimal(0)}
    if not root.exists():
        return spent
    for path in sorted(root.glob("*/manifest.json")):
        try:
            m = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(m, dict):
                raise ValueError("manifest 가 객체가 아니다")
            cost = _money(m["cost_usd"])
            run_stage, run_loop = m["stage"], m.get("loop_id")
            if run_stage not in STAGES:
                raise ValueError("알 수 없는 stage")
        except (OSError, ValueError, KeyError) as e:
            raise ValueError(f"manifest 를 읽을 수 없다: {path.parent.name}") from e
        spent["project"] += cost
        if run_stage == "baseline" and stage == "baseline":
            spent["baseline"] += cost
        if run_stage == "loop" and stage == "loop" and run_loop == loop_id:
            spent["loop"] += cost
    return spent


def read_trajectories(run_dir: Path) -> list[dict]:
    """저장된 궤적을 읽는다. 옛 키 `step_limit_hit` 로 저장된 결과도 새 키(`step_limit_reached`)로 바꿔 돌려주고, 없는 새 키는 False 로 채운다."""
    rows = []
    for line in (run_dir / "trajectories.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        legacy = row.pop("step_limit_hit", None)
        if legacy is not None:
            row.setdefault("step_limit_reached", bool(legacy))
        row.setdefault("step_limit_reached", False)
        row.setdefault("forced_final", False)
        row.setdefault(
            "faults_injected", 0
        )  # 옛 결과(오류 주입 기록이 생기기 전)는 0·빈 목록으로 읽는다
        row.setdefault("fault_tools", [])
        rows.append(row)
    return rows
