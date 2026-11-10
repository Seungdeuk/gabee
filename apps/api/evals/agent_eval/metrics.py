"""채점 결과를 지표로 모은다(docs/requirements/agent-eval.md 의 '지표'). LLM·DB 를 부르지 않는 순수 함수다.

반복 실행(`--repeat 3`)이 있으면 두 가지로 센다.
- Task Success Rate: (사례, 반복) 한 번의 실행을 한 단위로 센 성공률. 같은 사례의 반복은 독립 시행이
  아니므로 신뢰구간을 붙이지 않는다.
- pass@all: 사례 단위. 그 사례의 반복이 모두 통과해야 통과. 신뢰구간을 붙인다.
"""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from .schema import Case, Observation
from .scoring import CaseResult


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% 윌슨 신뢰구간(기본 z=1.96). n 이 0 이면 구할 수 없다."""
    if n <= 0 or not 0 <= k <= n:
        raise ValueError("0 <= k <= n, n > 0 이어야 한다")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass(frozen=True)
class Rate:
    k: int
    n: int
    low: float | None = None  # 신뢰구간이 없는 지표는 None
    high: float | None = None

    @property
    def value(self) -> float | None:
        return self.k / self.n if self.n else None


def _rate(k: int, n: int, ci: bool = False) -> Rate:
    if ci and n:
        low, high = wilson_interval(k, n)
        return Rate(k, n, low, high)
    return Rate(k, n)


@dataclass(frozen=True)
class CaseRun:
    """한 사례의 실행 묶음. 반복마다 채점 결과와 관찰 결과가 하나씩 있다."""

    case: Case
    results: tuple[CaseResult, ...]
    observations: tuple[Observation, ...]

    def __post_init__(self) -> None:
        if not self.results or len(self.results) != len(self.observations):
            raise ValueError(
                f"{self.case.id}: 채점 결과와 관찰 결과의 수가 같고 1개 이상이어야 한다"
            )


@dataclass(frozen=True)
class Efficiency:
    llm_calls_mean: float | None
    steps_mean: float | None
    tokens_in_total: int
    tokens_out_total: int
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    step_limit: Rate  # 실행 단위


@dataclass(frozen=True)
class Breakdown:
    cases: int
    task_success_rate: Rate
    pass_at_all: Rate


@dataclass(frozen=True)
class Summary:
    cases: int
    runs: int
    task_success_rate: Rate
    pass_at_all: Rate
    tool_selection: Rate  # 사례 기준(반복이 모두 맞음)
    tool_precision: Rate  # 도구 이름 단위, 실행 전체 합
    tool_recall: Rate
    tool_argument_items: Rate  # 기대 호출 항목 기준, 실행 전체 합
    tool_argument_cases: Rate  # 기대 호출이 있는 사례 기준(반복이 모두 맞음)
    security_violation_cases: int  # 목표 0, 하드 게이트
    security_violation_runs: int
    same_toolset: Rate  # 반복이 2회 이상인 사례만
    efficiency: Efficiency
    by_category: dict[str, Breakdown]
    by_scenario: dict[str, Breakdown]
    failure_pareto: tuple[tuple[str, int], ...]

    def as_rows(self) -> list[tuple[str, float | int | None]]:
        """summary.csv 용으로 (이름, 값)을 평평하게 편다."""
        rows: list[tuple[str, float | int | None]] = [("cases", self.cases), ("runs", self.runs)]
        rates = {
            "task_success_rate": self.task_success_rate,
            "pass_at_all": self.pass_at_all,
            "tool_selection": self.tool_selection,
            "tool_precision": self.tool_precision,
            "tool_recall": self.tool_recall,
            "tool_argument_items": self.tool_argument_items,
            "tool_argument_cases": self.tool_argument_cases,
            "same_toolset": self.same_toolset,
            "step_limit_rate": self.efficiency.step_limit,
        }
        for name, r in rates.items():
            rows += [(name, r.value), (f"{name}_n", r.n)]
            if r.low is not None:
                rows += [(f"{name}_ci_low", r.low), (f"{name}_ci_high", r.high)]
        rows += [
            ("security_violation_cases", self.security_violation_cases),
            ("security_violation_runs", self.security_violation_runs),
            ("llm_calls_mean", self.efficiency.llm_calls_mean),
            ("steps_mean", self.efficiency.steps_mean),
            ("tokens_in_total", self.efficiency.tokens_in_total),
            ("tokens_out_total", self.efficiency.tokens_out_total),
            ("latency_p50_ms", self.efficiency.latency_p50_ms),
            ("latency_p95_ms", self.efficiency.latency_p95_ms),
        ]
        return rows


def _percentile(values: list[int], pct: int) -> int | None:
    """가장 가까운 순위(nearest-rank) 방식."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(pct / 100 * len(ordered))) - 1]


def _mean(values: list[int]) -> float | None:
    return sum(values) / len(values) if values else None


def _toolset(case: Case, obs: Observation) -> frozenset[str]:
    return frozenset(c.name for c in obs.calls if c.stage == case.agent_path)


def _expected_tools(case: Case) -> frozenset[str]:
    own = (c.tool for c in case.expect.calls if (c.stage or case.agent_path) == case.agent_path)
    return frozenset({*case.expect.tools.required, *own})


def _breakdown(runs: Sequence[CaseRun]) -> Breakdown:
    total = sum(len(r.results) for r in runs)
    passed = sum(res.passed for r in runs for res in r.results)
    all_pass = sum(all(res.passed for res in r.results) for r in runs)
    return Breakdown(len(runs), _rate(passed, total), _rate(all_pass, len(runs), ci=True))


def _group(runs: Sequence[CaseRun], key) -> dict[str, Breakdown]:
    groups: dict[str, list[CaseRun]] = {}
    for r in runs:
        groups.setdefault(key(r.case), []).append(r)
    return {k: _breakdown(v) for k, v in sorted(groups.items())}


def summarize(runs: Sequence[CaseRun]) -> Summary:
    """사례 묶음 전체의 지표. 분모는 사례 수(사례 기준 지표)이거나 실행 수(실행 기준 지표)다."""
    if not runs:
        raise ValueError("사례가 하나도 없다")
    pairs = [
        (r.case, res, obs) for r in runs for res, obs in zip(r.results, r.observations, strict=True)
    ]
    obs_all = [obs for _, _, obs in pairs]
    base = _breakdown(runs)

    expected_calls = [r for r in runs if r.case.expect.calls]
    items = [c for r in runs for res in r.results for c in res.calls]
    hits = got = want = 0
    for case, _, obs in pairs:
        called, expected = _toolset(case, obs), _expected_tools(case)
        hits += len(called & expected)
        got += len(called)
        want += len(expected)

    repeated = [r for r in runs if len(r.observations) >= 2]
    same = sum(len({_toolset(r.case, o) for o in r.observations}) == 1 for r in repeated)

    failed = [res for _, res, _ in pairs if not res.passed]
    pareto = Counter(t for res in failed for t in res.failure_types)
    latencies = [o.latency_ms for o in obs_all]
    eff = Efficiency(
        llm_calls_mean=_mean([o.llm_calls for o in obs_all]),
        steps_mean=_mean([o.steps for o in obs_all]),
        tokens_in_total=sum(o.tokens_in for o in obs_all),
        tokens_out_total=sum(o.tokens_out for o in obs_all),
        latency_p50_ms=_percentile(latencies, 50),
        latency_p95_ms=_percentile(latencies, 95),
        step_limit=_rate(sum(o.step_limit_hit for o in obs_all), len(obs_all)),
    )
    return Summary(
        cases=len(runs),
        runs=len(pairs),
        task_success_rate=base.task_success_rate,
        pass_at_all=base.pass_at_all,
        tool_selection=_rate(
            sum(all(res.tools_ok for res in r.results) for r in runs), len(runs), ci=True
        ),
        tool_precision=_rate(hits, got),
        tool_recall=_rate(hits, want),
        tool_argument_items=_rate(sum(c.passed for c in items), len(items)),
        tool_argument_cases=_rate(
            sum(all(res.calls_ok for res in r.results) for r in expected_calls),
            len(expected_calls),
            ci=True,
        ),
        security_violation_cases=sum(
            any(res.security_violations for res in r.results) for r in runs
        ),
        security_violation_runs=sum(bool(res.security_violations) for _, res, _ in pairs),
        same_toolset=_rate(same, len(repeated), ci=True),
        efficiency=eff,
        by_category=_group(runs, lambda c: c.category),
        by_scenario=_group(runs, lambda c: c.scenario or "legacy"),
        failure_pareto=tuple(sorted(pareto.items(), key=lambda kv: (-kv[1], kv[0]))),
    )
