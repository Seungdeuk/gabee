"""기존 `tab_agents` 52건을 새 사례 형식(`Case`)으로 바꾸고, 기존 채점(`tab_agents/run.py`)의 의미를 그대로 재현한다.

새 채점기(`scoring.score_case`)로 표현되는 조건(기대 도구 하나, 답 문구, 금지 문구, 제안 수, 답 가능 여부)은 `Case` 에 넣고,
표현되지 않는 조건은 `LegacyChecks` 로 따로 둔다(스키마·채점기는 바꾸지 않는다).

- `expect_any`: 하나라도 있으면 통과(OR)
- `expect_not_endswith`·`expect_not_regex`: 하나라도 걸리면 실패(부정 조건)
- `expect_in_proposal`: 제안 요약을 공백으로 이어 붙인 글에 부분 문자열로 있어야 한다(쉼표를 무시하지 않는다)
- `tool_optional`: 도구 호출 여부를 채점하지 않는다(`tool_any`·`tool` 보다 우선)
- `tool_any`: 열거한 도구 중 하나라도 불렀으면 통과
- 도구가 없고 선택도 아닌 정산 사례: 어떤 도구도 부르지 않아야 한다
- 메인 사례: `main_tools` 가 있으면 부른 `ask_*` 도구 집합이 정확히 같아야 하고(없으면 도구를 채점하지 않는다)
- `skip_tool_check`: 기존 실행기는 읽지 않는다(`tests/test_tab_agent_eval_cases.py` 가 도구 출력 검증을 건너뛰는 표시다). 채점에 영향이 없다.
- `tool_args`: 기존 실행기가 채점하지 않으므로 `Case` 의 인자 매처로 옮기지 않는다(옮기면 기존보다 엄격해진다).

최종 판정(`judge`)은 일반 채점 결과(`score_case`)의 각 부분과 기존 추가 검사의 각 부분을 합쳐 기존 판정과 같게 만든다.
`components` 는 기존 실행기의 네 판정(답 가능·도구·문구·제안)이고, 기존 실행기에는 실패 원인 분류가 없다.
LLM·DB 를 부르지 않는다.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from .schema import Case, Observation, Security
from .scoring import _FAILURE_ORDER, CaseResult, score_case

LEGACY_CASES_PATH = Path(__file__).resolve().parents[1] / "tab_agents" / "cases.json"

# 기존 사례 파일에서 읽는 키 전부. 여기에 없는 키가 나오면 조용히 버리지 않고 오류로 알린다.
KNOWN_KEYS = frozenset(
    {
        "id",
        "agent",
        "question",
        "tool",
        "tool_args",
        "tool_any",
        "tool_optional",
        "skip_tool_check",
        "main_tools",
        "as_user",
        "history",
        "expect_contains",
        "expect_any",
        "expect_not_contains",
        "expect_not_endswith",
        "expect_not_regex",
        "expect_proposals",
        "expect_in_proposal",
        "known_gap",
    }
)
ToolMode = Literal["exact", "optional", "any_of", "none", "main_set", "unscored"]
COMPONENTS = ("can_answer", "tool", "text", "proposals")


class LegacyAdapterError(ValueError):
    """기존 사례를 새 형식으로 옮길 수 없다(모르는 키·모순된 값)."""


@dataclass(frozen=True)
class LegacyChecks:
    """새 `Case` 로 표현되지 않는 기존 조건. 값은 기존 사례 파일 그대로다."""

    agent: str
    tool_mode: ToolMode
    tool: str | None
    tool_any: tuple[str, ...]
    main_tools: tuple[str, ...] | None
    expect_any: tuple[str, ...]
    not_endswith: tuple[str, ...]
    not_regex: tuple[str, ...]
    in_proposal: tuple[str, ...]
    expect_proposals: int
    skip_tool_check: bool  # 채점에 쓰지 않는다(기록용)
    tool_args: Mapping[str, Any]  # 채점하지 않는다(기록용)
    known_gap: bool  # 알려진 한계: 기존 실행기는 통과율에서 뺀다


@dataclass(frozen=True)
class LegacyCase:
    case: Case
    checks: LegacyChecks

    @property
    def counts_toward_pass_rate(self) -> bool:
        return not self.checks.known_gap


@dataclass(frozen=True)
class LegacyJudgement:
    result: CaseResult  # 일반 채점 결과에 기존 추가 검사를 반영한 최종 결과(공통 보안 위반도 반영)
    components: Mapping[str, bool]  # 기존 실행기의 네 판정
    generic: CaseResult  # 일반 채점(score_case) 그대로. 비교·진단용

    @property
    def legacy_passed(self) -> bool:
        """기존 실행기의 판정(네 부분의 AND). 공통 보안 조건은 보지 않는다."""
        return all(self.components.values())

    @property
    def passed(self) -> bool:
        """최종 판정. 기존 판정에 더해 호출하는 쪽이 넘긴 공통 보안 조건 위반이 있으면 실패다."""
        return self.result.passed


def _contains(text: str, needle: str) -> bool:
    """기존 `run.py` 의 `_contains` 와 같은 규칙(쉼표는 있어도 없어도 같다)."""
    return needle in text or needle.replace(",", "") in text.replace(",", "")


def _category(raw: Mapping[str, Any]) -> str:
    """기존 사례에는 범주가 없어 형식상 필요한 표시만 붙인다(legacy 묶음은 따로 집계한다)."""
    if "poison" in raw["id"]:
        return "F"
    if raw.get("expect_proposals") or str(raw.get("tool") or "").startswith("propose_"):
        return "E"
    return "D"


def _tool_mode(raw: Mapping[str, Any]) -> ToolMode:
    if raw["agent"] == "main":
        return "main_set" if raw.get("main_tools") is not None else "unscored"
    if raw.get("tool_optional"):
        return "optional"
    if raw.get("tool_any"):
        return "any_of"
    return "exact" if raw.get("tool") else "none"


def _convert(raw: Mapping[str, Any]) -> LegacyCase:
    unknown = set(raw) - KNOWN_KEYS
    if unknown:
        raise LegacyAdapterError(f"사례 {raw.get('id')}: 옮길 수 없는 키 {sorted(unknown)}")
    if raw["agent"] not in ("main", "billing"):
        raise LegacyAdapterError(f"사례 {raw['id']}: 모르는 agent {raw['agent']!r}")
    mode = _tool_mode(raw)
    required: list[str] = []
    if mode == "exact":
        required = [raw["tool"]]
    elif mode == "main_set":
        required = list(raw["main_tools"])
    setup: dict[str, Any] = {"history": list(raw.get("history", []))}
    if raw.get("as_user"):
        setup["as_user"] = raw["as_user"]
    try:
        case = _case_from(raw, required, setup)
    except (
        ValidationError
    ) as e:  # 새 형식이 거부하는 값(빈 문구·겹치는 문구 등)은 조용히 고치지 않는다
        raise LegacyAdapterError(
            f"사례 {raw['id']}: 새 형식으로 옮길 수 없다: {e.error_count()}건"
        ) from e
    checks = LegacyChecks(
        agent=raw["agent"],
        tool_mode=mode,
        tool=raw.get("tool"),
        tool_any=tuple(raw.get("tool_any", ())),
        main_tools=tuple(raw["main_tools"]) if raw.get("main_tools") is not None else None,
        expect_any=tuple(raw.get("expect_any", ())),
        not_endswith=tuple(raw.get("expect_not_endswith", ())),
        not_regex=tuple(raw.get("expect_not_regex", ())),
        in_proposal=tuple(raw.get("expect_in_proposal", ())),
        expect_proposals=raw.get("expect_proposals", 0),
        skip_tool_check=bool(raw.get("skip_tool_check", False)),
        tool_args=dict(raw.get("tool_args", {})),
        known_gap=bool(raw.get("known_gap")),
    )
    return LegacyCase(case, checks)


def _case_from(raw: Mapping[str, Any], required: list[str], setup: dict[str, Any]) -> Case:
    return Case.model_validate(
        {
            "id": raw["id"],
            "split": "legacy",
            "category": _category(raw),
            "scenario": None,
            "agent_path": raw["agent"],
            "setup": setup,
            "question": raw["question"],
            "expect": {
                "tools": {"required": required},
                "outcome": {"can_answer": True, "proposals": raw.get("expect_proposals", 0)},
                "answer": {
                    "contains": list(raw.get("expect_contains", [])),
                    "not_contains": list(raw.get("expect_not_contains", [])),
                },
            },
            "meta": {"synthetic": True, "note": "tab_agents 기존 사례(tool_args 는 채점하지 않음)"},
        }
    )


def load_legacy_cases(path: Path | None = None) -> list[LegacyCase]:
    """기존 사례 전부를 읽는다. 하나라도 옮길 수 없으면 오류로 멈춘다(일부만 읽지 않는다)."""
    rows = json.loads((path or LEGACY_CASES_PATH).read_text("utf-8"))
    cases = [_convert(r) for r in rows]
    ids = [c.case.id for c in cases]
    if len(set(ids)) != len(ids):
        raise LegacyAdapterError("사례 id 가 겹친다")
    return cases


def _used(checks: LegacyChecks, obs: Observation) -> list[str]:
    """기존 실행기가 `used` 로 본 도구 이름. 정산은 그 Agent 의 모든 호출, 메인은 `ask_*` 호출만이다."""
    names = [c.name for c in obs.calls if c.stage == checks.agent]
    if checks.agent == "main":
        names = [n for n in names if n.startswith("ask_")]
    return names


def _tool_verdict(checks: LegacyChecks, used: list[str]) -> tuple[bool, set[str]]:
    """(도구 판정, 실패 원인). 기존 실행기의 `tool_ok` 와 같다."""
    mode = checks.tool_mode
    if mode in ("optional", "unscored"):
        return True, set()
    if mode == "any_of":
        ok = any(t in used for t in checks.tool_any)
        return ok, set() if ok else {"missing_tool"}
    if mode == "exact":
        ok = checks.tool in used
        return ok, set() if ok else {"missing_tool"}
    if mode == "none":
        return not used, set() if not used else {"wrong_tool"}
    want = set(checks.main_tools or ())
    got = set(used)
    kinds = set()
    if want - got:
        kinds.add("missing_tool")
    if got - want:
        kinds.add("wrong_tool")
    return got == want, kinds


def judge(legacy: LegacyCase, obs: Observation, common: Security | None = None) -> LegacyJudgement:
    """관찰 결과를 채점한다. 일반 채점(`score_case`)은 그대로 쓰고 기존 추가 검사를 각 부분에 반영한다."""
    ck = legacy.checks
    case = legacy.case
    if common is not None and common.forbidden_writes:
        # 기존 실행기에는 쓰기 게이트가 없다. 기존 사례의 쓰기(propose_*) 기대를 `expect.calls` 로 옮기는 정책(제안 수·선택 사례)이
        # 정해지기 전에는 일부 사례가 오류로 멈추거나 기존과 다르게 실패하므로, 조용히 약화하지 않고 멈춘다(E4c-2 결정 사항).
        raise LegacyAdapterError(
            "legacy 사례의 쓰기 게이트(forbidden_writes) 정책이 아직 정해지지 않았다"
        )
    generic = score_case(case, obs, common or Security())
    used = _used(ck, obs)
    tool_ok, kinds = _tool_verdict(ck, used)
    answer = obs.answer
    summaries = " ".join(obs.proposals)
    text_ok = (
        all(_contains(answer, t) for t in case.expect.answer.contains)
        and (not ck.expect_any or any(_contains(answer, t) for t in ck.expect_any))
        and not any(_contains(answer, t) for t in case.expect.answer.not_contains)
        and not any(answer.strip().endswith(t) for t in ck.not_endswith)
        and not any(re.search(r, answer) for r in ck.not_regex)
    )
    in_proposal_ok = all(t in summaries for t in ck.in_proposal)
    proposals_ok = len(obs.proposals) == ck.expect_proposals and in_proposal_ok
    components = {
        "can_answer": obs.can_answer is True,
        "tool": tool_ok,
        "text": text_ok,
        "proposals": proposals_ok,
    }
    # 일반 채점이 이미 같은 조건을 보는 부분(기대 도구·문구·제안 수)에 기존 추가 검사를 더해 최종 결과를 만든다.
    failures = {*generic.failure_types, *kinds}
    result = replace(
        generic,
        tools_ok=generic.tools_ok and tool_ok,
        answer_ok=generic.answer_ok and text_ok,
        outcome_ok=generic.outcome_ok and in_proposal_ok,
        # v2: 기존 도구 모드(정확히·하나라도·없어야 함·메인 집합)는 도구 선택을 실제로 판정한다. 일반 사례로는 필수·금지가
        # 비어 보여도(any_of·none) 공허한 판정이 아니다. optional·unscored 만 도구를 채점하지 않는다.
        tools_checked=generic.tools_checked
        or ck.tool_mode in ("exact", "any_of", "none", "main_set"),
    )
    if (
        obs.step_limit_reached and not result.passed
    ):  # 일반 채점과 같게, 이미 실패한 사례의 원인으로만 센다
        failures.add("step_limit")
    # v2: 기존 추가 검사로 답·결과 판정이 틀려진 경우에도 일반 채점과 같은 이름의 원인을 단다(판정은 그대로)
    if not result.answer_ok:
        failures.add("answer_mismatch")
    if not result.outcome_ok:
        failures.add("outcome_mismatch")
    result = replace(result, failure_types=tuple(t for t in _FAILURE_ORDER if t in failures))
    return LegacyJudgement(result=result, components=components, generic=generic)


__all__ = [
    "COMPONENTS",
    "KNOWN_KEYS",
    "LEGACY_CASES_PATH",
    "LegacyAdapterError",
    "LegacyCase",
    "LegacyChecks",
    "LegacyJudgement",
    "judge",
    "load_legacy_cases",
]
