"""저장된 실행 결과를 다른 채점 기준·사례로 다시 채점한다(소급 재채점). LLM·네트워크를 부르지 않는다.

    python -m evals.agent_eval.rescore <원본 결과 폴더> --cases-file <라벨>=<사례 JSON> [--cases-file ...]

원본은 읽기만 하고 절대 고치지 않는다. 라벨마다 `results/_rescore/rescore-<원본 run id>-<라벨>/` 에 따로 저장하고(manifest 에
원본 run id·채점기 버전·사례 해시·"소급 재채점" 표시), 라벨 전체를 한 표로 비교한 `comparison-<원본>.json` 도 쓴다.

## 읽는 법: 이것은 Agent 성능 개선이 아니다
- 같은 관찰(모델이 실제로 한 행동)을 다른 기준으로 다시 본 것이다. 사례·채점 기준을 고친 뒤의 성공률 상승은 **사후 보정**이지
  Agent 가 나아진 것이 아니다. Agent 의 개선은 고친 기준으로 새로 실행한 결과로만 말한다.
- 저장된 관찰은 원래 관찰보다 정보가 적다: 답은 개인정보 스크러버를 거친 뒤 앞 500자, 도구 인자 값은 스크러버를 거쳐 200자,
  제안은 개수만 저장돼 있다. 그래서 **원래 보안 위반은 재채점이 절대 약화하지 못한다**: 원본 행에 적힌 보안 위반은 항상 유지하고
  (새 기준이 더 찾으면 더하기만 한다), 원본이 판정하지 못한 행(관찰 누락)은 실패로 둔다.
- 원본의 판정과 어긋나는 행은 `reproduced=false` 로 보고한다(어긋남을 숨기지 않는다).
- 검증·테스트 분할의 결과나 사례 파일은 열지 않는다(원본 manifest 가 dev 만 가리켜야 하고, 사례 파일은 열린 경로의 dev 목록이어야 한다).
"""

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from . import fault_injection, metrics, scoring, store
from .schema import Case, Observation, ToolCall, dump_case

SOURCE_FILES = ("manifest.json", "cases.jsonl", "trajectories.jsonl")
ROW_KEYS = ("passed", "tools_ok", "calls_ok", "outcome_ok", "answer_ok")
NEW_FAILURE_TYPES = frozenset({"answer_mismatch", "outcome_mismatch"})  # v2 에서 더해진 유형
TOOL_KINDS = frozenset({"missing_tool", "wrong_tool"})
_LABEL = re.compile(r"[a-z0-9][a-z0-9_-]{0,19}")
RESERVED_LABELS = frozenset({"original"})
EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_OUT = (
    EVAL_DIR / "results" / "_rescore"
)  # opening_spent 가 읽지 않는 깊이(실제 지출 누적에 섞이지 않는다)

Judge = Callable[[Case, Observation], scoring.CaseResult]
# 원본 보안 위반 표기(`scoring._security`·`runner._with_write_attempts`)가 가리키는 실패 유형
_SECURITY_KIND = (("tool:", "wrong_tool"), ("write:", "unapproved_write"))


class RescoreError(Exception):
    pass


@dataclass(frozen=True)
class Row:
    """원본 한 행(사례·반복)과 다시 채점한 결과."""

    case_id: str
    repeat: int
    original: Mapping[str, Any]  # 원본 cases.jsonl 행
    result: scoring.CaseResult
    limits: tuple[str, ...]  # 저장된 관찰이 원래보다 정보가 적어 어긋날 수 있는 이유

    @property
    def reproduced(self) -> bool | None:
        """다시 채점한 판정이 원본과 같은가. 새 유형(answer·outcome_mismatch)은 원본에 없으므로 빼고 비교한다."""
        want = {k: self.original.get(k) for k in ROW_KEYS}
        got = {
            "passed": self.result.passed,
            "tools_ok": self.result.tools_ok,
            "calls_ok": self.result.calls_ok,
            "outcome_ok": self.result.outcome_ok,
            "answer_ok": self.result.answer_ok,
        }
        # 새 유형은 v1 원본에 없으므로 양쪽에서 빼고 비교한다(원본이 v2 로 저장된 결과여도 같은 기준)
        same_types = sorted(set(self.result.failure_types) - NEW_FAILURE_TYPES) == sorted(
            set(self.original.get("failure_types", ())) - NEW_FAILURE_TYPES
        )
        same_security = list(self.result.security_violations) == list(
            self.original.get("security_violations", ())
        )
        return want == got and same_types and same_security


@dataclass(frozen=True)
class Rescored:
    source_id: str
    label: str
    cases_hash: str
    rows: tuple[Row, ...]
    runs: tuple[metrics.CaseRun, ...]
    manifest: Mapping[str, Any]  # 원본 manifest

    def summary(self) -> metrics.Summary:
        return metrics.summarize(self.runs)

    @property
    def passed(self) -> int:
        return sum(r.result.passed for r in self.rows)

    @property
    def reproduced_all(self) -> bool:
        return all(r.reproduced for r in self.rows)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RescoreError(f"{path.name} 를 읽을 수 없다: {e}") from e


def _read_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_source(source: Path) -> tuple[dict, list[dict], list[dict]]:
    """원본 결과를 읽는다(읽기만). 검증·테스트 분할이 섞였거나 파일이 없거나 형식이 이상하면 거부한다."""
    missing = [n for n in SOURCE_FILES if not (source / n).is_file()]
    if missing:
        raise RescoreError(f"원본 결과 폴더에 파일이 없다: {missing}")
    manifest = _read_json(source / "manifest.json")
    run_id = manifest.get("run_id") if isinstance(manifest, dict) else None
    if not (isinstance(run_id, str) and store.RUN_ID.fullmatch(run_id)):
        raise RescoreError("원본 manifest 의 run_id 형식이 맞지 않는다")
    if "rescored_from" in manifest:
        raise RescoreError(
            "재채점 결과를 다시 재채점하지 않는다(원본 코드 커밋 기록이 흐려진다). 처음 실행 결과를 쓴다"
        )
    splits = set(manifest.get("split_hashes", {}))
    if splits != {"dev"}:
        raise RescoreError(
            f"dev 분할 결과만 다시 채점한다(원본 split_hashes: {sorted(splits)}). 검증·테스트 결과는 열지 않는다"
        )
    originals, trajectories = _read_rows(source / "cases.jsonl"), store.read_trajectories(source)
    _check_complete(manifest, originals, trajectories)
    return manifest, originals, trajectories


def _check_complete(
    manifest: Mapping[str, Any], originals: Sequence[Mapping], trajectories: Sequence[Mapping]
) -> None:
    """원본이 끝까지 저장된 완전한 실행인지 본다. 실행기는 **모든 반복이 끝난 사례만** 저장하므로 저장된 사례는 반복 번호가
    0..repeats-1 로 빠짐없이 있고 사례 수는 manifest 와 같다. 중복·누락(양쪽 파일에서 같은 반복이 빠진 경우 포함)이 있으면
    미완료·변조된 결과일 수 있어 정상 완료나 100% 성공으로 집계하지 않고 거부한다."""
    repeats = manifest.get("repeats")
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise RescoreError("원본 manifest 의 repeats 가 1 이상의 정수가 아니다")
    keys: dict[str, set[tuple[str, int]]] = {}
    for name, rows in (("cases.jsonl", originals), ("trajectories.jsonl", trajectories)):
        seen: set[tuple[str, int]] = set()
        for row in rows:
            key = (str(row.get("case_id")), row.get("repeat"))
            if isinstance(key[1], bool) or not isinstance(key[1], int):
                raise RescoreError(f"{name}: 반복 번호가 정수가 아니다: {key[0]}")
            if key in seen:
                raise RescoreError(f"{name}: 같은 사례·반복이 두 번 있다: {key[0]} #{key[1]}")
            seen.add(key)
        keys[name] = seen
    if keys["cases.jsonl"] != keys["trajectories.jsonl"]:
        raise RescoreError("cases.jsonl 과 trajectories.jsonl 의 행이 서로 다르다")
    by_case: dict[str, set[int]] = {}
    for case_id, repeat in keys["cases.jsonl"]:
        by_case.setdefault(case_id, set()).add(repeat)
    want = set(range(repeats))
    bad = sorted(c for c, got in by_case.items() if got != want)
    if bad:
        raise RescoreError(
            f"사례의 반복 번호가 manifest.repeats({repeats})의 0..{repeats - 1} 과 다르다(누락·초과): {bad[:5]}"
        )
    stored = manifest.get("cases")
    if isinstance(stored, int) and not isinstance(stored, bool) and stored != len(by_case):
        raise RescoreError(
            f"저장된 사례 수({len(by_case)})가 manifest.cases({stored})와 다르다(사례 행 누락)"
        )


def observation_of(row: Mapping[str, Any]) -> tuple[Observation, tuple[str, ...]]:
    """저장된 궤적 한 행을 관찰로 되돌린다. 돌려주는 것: (관찰, 정보가 줄어든 이유 목록)."""
    limits: list[str] = []
    answer = str(row.get("answer", ""))
    if len(answer) >= store.ANSWER_MAX:
        limits.append("answer_truncated")
    proposals = int(row.get("proposals") or 0)
    if proposals:
        limits.append(
            "proposal_text_missing"
        )  # 제안 문장은 개수만 저장돼 있어 문구 검사를 다시 할 수 없다
    if any(
        isinstance(v, str) and len(v) >= store.ARG_VALUE_MAX
        for c in row.get("calls", ())
        for v in (c.get("args") or {}).values()
    ):
        limits.append("args_truncated")
    if (
        fault_injection.specs_for(str(row.get("case_id", "")))
        and int(row.get("faults_injected") or 0) == 0
    ):
        # 오류 주입 명세가 있는 사례인데 주입 기록이 0(옛 결과는 주입 장치가 없었다): 도구 오류 복구를 검증한 결과가 아니다
        limits.append("fault_not_injected")
    obs = Observation(
        calls=[
            ToolCall(
                stage=c["stage"],
                name=c["name"],
                args=c.get("args") or {},
                is_error=bool(c.get("is_error")),
                superseded=bool(c.get("superseded")),
            )
            for c in row.get("calls", ())
        ],
        answer=answer,
        can_answer=row.get("can_answer"),
        proposals=["(저장되지 않음)"] * proposals,
        posted_to_room=row.get("posted_to_room"),
        card_kind=row.get("card_kind"),
        steps=row.get("steps", 0),
        llm_calls=row.get("llm_calls", 0),
        tokens_in=row.get("tokens_in", 0),
        tokens_out=row.get("tokens_out", 0),
        latency_ms=row.get("latency_ms", 0),
        step_limit_reached=bool(row.get("step_limit_reached")),
        forced_final=bool(row.get("forced_final")),
        faults_injected=int(row.get("faults_injected") or 0),
        fault_tools=list(row.get("fault_tools") or []),
    )
    return obs, tuple(limits)


def cases_fingerprint(cases: Sequence[Case]) -> str:
    """사례 내용의 해시(사례 id 순서와 무관, 채점기 v2 의 빈 선택 필드는 뺀 정규 JSON)."""
    body = sorted(json.dumps(dump_case(c), sort_keys=True, ensure_ascii=False) for c in cases)
    return hashlib.sha256("\n".join(body).encode("utf-8")).hexdigest()


def is_unjudged(original: Mapping[str, Any]) -> bool:
    """실행기가 관찰 누락 반복에 저장한 자리표시 결과인가: 도구 판정이 거짓인데 도구 원인(missing·wrong_tool)이 없다.
    진짜 채점의 도구 실패는 항상 도구 원인이 붙으므로 이 조합은 판정하지 못한 행이다."""
    types = set(original.get("failure_types", ()))
    return original.get("tools_ok") is False and not types & TOOL_KINDS


def never_weaker(original: Mapping[str, Any], result: scoring.CaseResult) -> scoring.CaseResult:
    """원본 행에 적힌 보안 위반은 재채점으로 사라지지 않는다. 새 기준이 더 찾으면 더하기만 한다."""
    kept = [str(v) for v in original.get("security_violations", ())]
    merged = tuple(dict.fromkeys([*kept, *result.security_violations]))
    if merged == result.security_violations:
        return result
    kinds = set(result.failure_types)
    for label in kept:
        kinds.add(
            next(
                (kind for prefix, kind in _SECURITY_KIND if label.startswith(prefix)), "scope_leak"
            )
        )
    return replace(
        result,
        security_violations=merged,
        failure_types=tuple(t for t in scoring._FAILURE_ORDER if t in kinds),
    )


def _keep_step_limit(result: scoring.CaseResult, obs: Observation) -> scoring.CaseResult:
    """원본 보안 위반을 되살려 실패가 된 행에도 `score_case` 와 같은 규칙으로 `step_limit` 원인을 단다: 단계 상한에 닿았고
    **최종 결과가 실패일 때만**(정상 완료 사례에는 붙이지 않는다). 새 판정이 통과였다면 `score_case` 가 못 붙였던 원인이다."""
    if not obs.step_limit_reached or result.passed or "step_limit" in result.failure_types:
        return result
    kinds = {*result.failure_types, "step_limit"}
    return replace(result, failure_types=tuple(t for t in scoring._FAILURE_ORDER if t in kinds))


def rescore(
    source: Path, cases: Sequence[Case], *, label: str, judge: Judge | None = None
) -> Rescored:
    """원본 결과를 `cases` 와 현재 채점기로 다시 채점한다. 원본은 고치지 않는다. 원본의 사례가 `cases` 에 없으면 거부한다."""
    if not _LABEL.fullmatch(label) or label in RESERVED_LABELS:
        raise RescoreError("라벨은 소문자·숫자·_- 만, 20자 이하(original 은 예약어)")
    manifest, originals, trajectories = load_source(source)
    by_id = {c.id: c for c in cases}
    unknown = sorted({str(r["case_id"]) for r in originals} - set(by_id))
    if unknown:
        raise RescoreError(f"원본의 사례가 사례 파일에 없다: {unknown}")
    # 중복·누락·두 파일 불일치는 `load_source` 의 `_check_complete` 가 이미 거부했다(여기서는 키 하나에 행 하나)
    traj = {(t["case_id"], t["repeat"]): t for t in trajectories}
    if judge is None:
        judge = _default_judge()
    rows: list[Row] = []
    grouped: dict[str, list[Row]] = {}
    observed: dict[tuple[str, int], Observation] = {}
    for original in sorted(originals, key=lambda r: (r["case_id"], r["repeat"])):
        case_id, repeat = str(original["case_id"]), int(original["repeat"])
        case = by_id[case_id]
        obs, limits = observation_of(traj[(case_id, repeat)])
        if is_unjudged(original):
            # 관찰 누락으로 판정하지 못한 행은 저장된 부분 관찰로 다시 판정하지 않고 실패로 둔다
            tools = case.expect.tools
            result = scoring.CaseResult(
                case_id, False, (), False, False, (), (), bool(tools.required or tools.forbidden)
            )
            limits = (*limits, "original_not_judged")
        else:
            fresh = judge(case, obs)
            result = _keep_step_limit(never_weaker(original, fresh), obs)
            if result.security_violations != fresh.security_violations:
                # 새 판정이 못 찾은 원래 보안 위반을 유지했다(스크러버·절단으로 증거가 줄었을 수 있다)
                limits = (*limits, "security_union_with_original")
        row = Row(case_id, repeat, original, result, limits)
        rows.append(row)
        grouped.setdefault(case_id, []).append(row)
        observed[(case_id, repeat)] = obs
    runs = tuple(
        metrics.CaseRun(
            by_id[case_id],
            tuple(r.result for r in group),
            tuple(observed[(r.case_id, r.repeat)] for r in group),
        )
        for case_id, group in grouped.items()
    )
    used = {r.case_id: by_id[r.case_id] for r in rows}
    return Rescored(
        str(manifest["run_id"]),
        label,
        cases_fingerprint(list(used.values())),
        tuple(rows),
        runs,
        manifest,
    )


def _default_judge() -> Judge:
    """실행기와 같은 판정(공통 보안·읽기 별칭·일정 쓰기 시도 포함). 앱을 불러오므로 환경 준비 뒤에만 부른다."""
    from . import runner

    def judge(case: Case, obs: Observation) -> scoring.CaseResult:
        result = runner.judge(case, obs).result
        written = sorted(set(runner.schedule_write_calls(obs)))  # 실행기 `_run_one` 과 같은 단계
        return runner._with_write_attempts(result, written) if written else result

    return judge


def comparison(source: Path, variants: Sequence[Rescored]) -> dict[str, Any]:
    """원본과 라벨별 재채점을 한 표로. 같은 사례 id 로 묶고 라벨은 `variants` 아래에 둔다(원본 열과 섞이지 않는다)."""
    labels = [v.label for v in variants]
    if len(set(labels)) != len(labels):
        raise RescoreError(f"라벨이 겹친다: {labels}")
    manifest, originals, _ = load_source(source)
    table = []
    for original in sorted(originals, key=lambda r: (r["case_id"], r["repeat"])):
        key = (original["case_id"], original["repeat"])
        entry: dict[str, Any] = {
            "case_id": original["case_id"],
            "repeat": original["repeat"],
            "original": {
                k: original.get(k) for k in (*ROW_KEYS, "failure_types", "security_violations")
            },
            "variants": {},
        }
        for v in variants:
            row = next(r for r in v.rows if (r.case_id, r.repeat) == key)
            entry["variants"][v.label] = {
                "passed": row.result.passed,
                **{k: getattr(row.result, k) for k in ROW_KEYS if k != "passed"},
                "failure_types": list(row.result.failure_types),
                "security_violations": list(row.result.security_violations),
                "tools_checked": row.result.tools_checked,
                "reproduced_original": row.reproduced,
                "limits": list(row.limits),
            }
        table.append(entry)
    aggregates: dict[str, Any] = {}
    for v in variants:
        s = v.summary()
        aggregates[v.label] = {
            "passed": v.passed,
            "n": len(v.rows),
            "task_success_rate": s.task_success_rate.value,
            "tool_selection": s.tool_selection.value,
            "tool_selection_n": s.tool_selection.n,
            "tool_selection_checked": s.tool_selection_checked.value,
            "tool_selection_checked_n": s.tool_selection_checked.n,
            "tool_precision": s.tool_precision.value,
            "tool_precision_n": s.tool_precision.n,
            "tool_recall": s.tool_recall.value,
            "tool_argument_cases": s.tool_argument_cases.value,
            "tool_argument_cases_n": s.tool_argument_cases.n,
            "allowed_calls_excluded": s.allowed_calls_excluded,
            "security_violation_cases": s.security_violation_cases,
            "reproduces_original": v.reproduced_all,
            "cases_hash": v.cases_hash,
        }
    return {
        "kind": "retroactive_rescore_comparison",
        "notice": (
            "소급 재채점이다. 사례·채점 기준을 고친 뒤의 성공률 변화는 사후 보정이며 Agent 성능 개선이 아니다. "
            "저장된 관찰(스크러버를 거친 답 500자·인자 200자·제안 개수)로 다시 본 것이라 원래 보안 위반은 항상 유지하고 "
            "관찰 누락 행은 실패로 둔다."
        ),
        "source_run_id": manifest["run_id"],
        "source_git_commit": manifest.get("git_commit"),
        "scorer_version": scoring.SCORER_VERSION,
        "original": {
            "passed": sum(bool(r.get("passed")) for r in originals),
            "n": len(originals),
        },
        "variants": aggregates,
        "rows": table,
    }


def run_id_of(rescored: Rescored) -> str:
    return f"rescore-{rescored.source_id}-{rescored.label}"


def write(rescored: Rescored, out_root: Path, *, git_commit: str) -> Path:
    """한 라벨의 재채점을 `out_root/rescore-<원본>-<라벨>/` 에 저장한다(이미 있으면 거부, 원본은 건드리지 않는다)."""
    s = rescored.summary()
    manifest = {
        "run_id": run_id_of(rescored),
        "stage": "other",
        "model": rescored.manifest["model"],
        "git_commit": git_commit,
        "prompt_hash": rescored.manifest["prompt_hash"],
        # 원본의 dev 사례 id 해시다(사례 내용이 아니다). 재채점에 쓴 사례의 내용은 `cases_hash` 로 가린다.
        "split_hashes": rescored.manifest["split_hashes"],
        "seed": rescored.manifest["seed"],
        "repeats": rescored.manifest["repeats"],
        "rescored_from": rescored.source_id,
        "source_git_commit": rescored.manifest["git_commit"],
        "scorer_version": scoring.SCORER_VERSION,
        "cases_hash": rescored.cases_hash,
        "rescore_label": rescored.label,
    }
    rows = [(f"metrics.{name}", value) for name, value in s.as_rows()]
    return store.write_run(out_root, manifest, rescored.runs, [], rows)


def _parse_variant(text: str) -> tuple[str, Path]:
    label, sep, raw = text.partition("=")
    if not sep or not label or not raw:
        raise argparse.ArgumentTypeError("--cases-file 은 <라벨>=<사례 JSON 경로> 형식이다")
    return label, Path(raw)


def _check_destinations(
    source: Path, out_root: Path, source_id: str, labels: Sequence[str]
) -> Path:
    """아무것도 쓰기 전에 모든 목적지를 검사한다(일부만 쓰이고 끝나는 일이 없게). 돌려주는 것: 비교 파일 경로."""
    if len(set(labels)) != len(labels):
        raise RescoreError(f"라벨이 겹친다: {list(labels)}")
    resolved_out, resolved_src = out_root.resolve(), source.resolve()
    if resolved_out == resolved_src or resolved_src in resolved_out.parents:
        raise RescoreError("--out-root 가 원본 결과 폴더 안이다(원본은 건드리지 않는다)")
    for label in labels:
        run_id = f"rescore-{source_id}-{label}"
        if not store.RUN_ID.fullmatch(run_id):
            raise RescoreError(f"재채점 run id 형식이 맞지 않는다(너무 길다?): {run_id}")
        if (out_root / run_id).exists():
            raise RescoreError(f"이미 있는 재채점 폴더다(덮어쓰지 않는다): {run_id}")
    out = out_root / f"comparison-{source_id}.json"
    if out.exists():
        raise RescoreError(f"이미 있는 비교 파일이다(덮어쓰지 않는다): {out.name}")
    return out


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m evals.agent_eval.rescore", description=__doc__.split("\n")[0]
    )
    p.add_argument("source", type=Path, help="원본 결과 폴더(읽기만 한다)")
    p.add_argument("--cases-file", action="append", type=_parse_variant, required=True)
    p.add_argument("--out-root", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)
    from . import cli  # 사례 파일 노출 가드·환경 준비·git 해시는 실행기와 같은 것을 쓴다

    tmp, cleanup = cli.prepare_environment(False)
    try:
        manifest, _, _ = load_source(args.source)
        labels = [label for label, _ in args.cases_file]
        out = _check_destinations(args.source, args.out_root, str(manifest["run_id"]), labels)
        variants = [
            rescore(args.source, cli._read_cases(path, "dev"), label=label)
            for label, path in args.cases_file
        ]
        report = comparison(args.source, variants)  # 쓰기 전에 모두 계산해 둔다
        commit = cli._git_commit()
        for v in variants:
            run_dir = write(v, args.out_root, git_commit=commit)
            print(
                f"[{v.label}] 통과 {v.passed}/{len(v.rows)} · 원본 판정 재현 {v.reproduced_all} → {run_dir}"
            )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"비교표: {out}")
        print(report["notice"])
    except (RescoreError, FileExistsError, ValueError, cli.Refusal) as e:
        message = e.message if isinstance(e, cli.Refusal) else e
        print(f"거부: {message}", file=sys.stderr)
        return 3
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
