"""지표 집계 시험(L0). 채점 결과를 직접 만들어 넣으므로 LLM·DB 가 필요 없다."""

import pytest

from evals.agent_eval.metrics import CaseRun, summarize, wilson_interval
from evals.agent_eval.schema import Case, Observation, Security, ToolCall
from evals.agent_eval.scoring import score_case

NONE = Security()


def _case(
    cid="c-1", category="C", scenario="single_tool", expect=None, split="dev", path="schedule"
):
    return Case.model_validate(
        {
            "id": cid,
            "split": split,
            "category": category,
            "scenario": scenario,
            "agent_path": path,
            "question": "내일 3시 치과 등록해줘",
            "expect": expect or {},
            "meta": {"synthetic": True},
        }
    )


def _obs(*names, **kw):
    return Observation(
        calls=[ToolCall(stage="schedule", name=n, args={"title": "치과"}) for n in names], **kw
    )


def _run(case, *observations):
    results = tuple(score_case(case, o, NONE) for o in observations)
    return CaseRun(case, results, tuple(observations))


REGISTER = {"tools": {"required": ["register"]}, "calls": [{"tool": "register", "args": []}]}
GOOD, BAD = _obs("register"), _obs()


def test_wilson_interval_known_values():
    low, high = wilson_interval(8, 10)
    assert (low, high) == (pytest.approx(0.490, abs=1e-3), pytest.approx(0.943, abs=1e-3))
    low, high = wilson_interval(0, 10)
    assert low == 0.0 and high == pytest.approx(0.278, abs=1e-3)
    assert wilson_interval(10, 10)[1] == 1.0
    for k, n in ((0, 0), (-1, 5), (6, 5)):
        with pytest.raises(ValueError):
            wilson_interval(k, n)


def test_task_success_rate_and_pass_at_all_are_separate_metrics():
    flaky = _run(_case("a", expect=REGISTER), GOOD, BAD, GOOD)  # 3번 중 2번 통과
    steady = _run(_case("b", expect=REGISTER), GOOD, GOOD, GOOD)
    s = summarize([flaky, steady])
    assert (s.cases, s.runs) == (2, 6)
    assert (s.task_success_rate.k, s.task_success_rate.n) == (5, 6)
    assert s.task_success_rate.low is None  # 반복은 독립 시행이 아니라 구간을 붙이지 않는다
    assert (s.pass_at_all.k, s.pass_at_all.n) == (1, 2)
    assert s.pass_at_all.low is not None and s.pass_at_all.low < 0.5 < s.pass_at_all.high


def test_single_repeat_makes_both_metrics_agree():
    s = summarize([_run(_case("a", expect=REGISTER), GOOD), _run(_case("b", expect=REGISTER), BAD)])
    assert s.task_success_rate.value == s.pass_at_all.value == 0.5


def test_tool_selection_precision_and_recall():
    case = _case("a", expect={"tools": {"required": ["register", "notify"]}})
    s = summarize([_run(case, _obs("register", "extra"))])
    assert (s.tool_precision.k, s.tool_precision.n) == (1, 2)  # 부른 도구 2개 중 기대한 것 1개
    assert (s.tool_recall.k, s.tool_recall.n) == (1, 2)  # 기대한 도구 2개 중 부른 것 1개
    assert (s.tool_selection.k, s.tool_selection.n) == (0, 1)
    ok = summarize([_run(_case("b", expect={"tools": {"required": ["register"]}}), GOOD)])
    assert ok.tool_precision.value == ok.tool_recall.value == 1.0 and ok.tool_selection.value == 1.0


def test_tool_argument_items_and_cases():
    case = _case(
        "a",
        expect={
            "calls": [
                {
                    "tool": "register",
                    "args": [{"arg": "title", "match": "contains", "value": "치과"}],
                },
                {
                    "tool": "register",
                    "args": [{"arg": "title", "match": "contains", "value": "안과"}],
                },
            ]
        },
    )
    s = summarize([_run(case, _obs("register", "register"))])  # 항목 2개 중 1개만 대응
    assert (s.tool_argument_items.k, s.tool_argument_items.n) == (1, 2)
    assert (s.tool_argument_cases.k, s.tool_argument_cases.n) == (0, 1)
    none = summarize([_run(_case("b"), GOOD)])  # 기대 호출이 없는 사례는 인자 지표의 분모에 없다
    assert none.tool_argument_items.n == 0 and none.tool_argument_cases.n == 0
    assert none.tool_argument_items.value is None


def test_security_violations_count_cases_and_runs():
    case = _case("a", expect={"security": {"forbidden_strings": ["김철수"]}})
    leak = Observation(answer="김철수 일정")
    s = summarize([_run(case, leak, Observation(), leak), _run(_case("b"), Observation())])
    assert (s.security_violation_cases, s.security_violation_runs) == (1, 2)


def test_same_toolset_only_counts_repeated_cases():
    one = summarize([_run(_case("a"), _obs("register"))])
    assert one.same_toolset.n == 0 and one.same_toolset.value is None
    steady = _run(_case("a"), _obs("register"), _obs("register"))
    drifting = _run(_case("b"), _obs("register"), _obs("delete"))
    s = summarize([steady, drifting, _run(_case("c"), _obs("register"))])
    assert (s.same_toolset.k, s.same_toolset.n) == (1, 2)


def test_efficiency_uses_nearest_rank_percentiles():
    obs = [
        Observation(
            latency_ms=ms,
            llm_calls=2,
            steps=1,
            tokens_in=10,
            tokens_out=5,
            step_limit_reached=ms >= 300,
            forced_final=ms == 400,
        )
        for ms in (100, 200, 300, 400)
    ]
    s = summarize([_run(_case(str(i)), o) for i, o in enumerate(obs)])
    e = s.efficiency
    assert (e.latency_p50_ms, e.latency_p95_ms) == (200, 400)
    assert (e.llm_calls_mean, e.steps_mean) == (2, 1)
    assert (e.tokens_in_total, e.tokens_out_total) == (40, 20)
    assert (e.step_limit.k, e.step_limit.n) == (2, 4)  # 단계 상한에 닿은 실행
    assert (e.forced_final.k, e.forced_final.n) == (1, 4)  # 그중 도구 없이 최종 답을 받은 실행
    rows = dict(s.as_rows())
    assert rows["step_limit_rate"] == 0.5 and rows["forced_final_rate"] == 0.25


def test_breakdown_by_category_and_scenario_includes_legacy():
    runs = [
        _run(_case("a", "A", "single_tool", REGISTER, split="legacy"), GOOD),
        _run(_case("b", "A", "clarify", REGISTER, split="legacy"), BAD),
        _run(_case("c", "B", None, REGISTER, split="legacy"), GOOD),
    ]
    s = summarize(runs)
    assert list(s.by_category) == ["A", "B"] and s.by_category["A"].cases == 2
    assert s.by_category["A"].pass_at_all.k == 1 and s.by_category["B"].pass_at_all.value == 1.0
    assert set(s.by_scenario) == {"single_tool", "clarify", "legacy"}


def test_failure_pareto_counts_each_type_once_per_failed_run_and_sorts():
    miss = _case("a", expect={"tools": {"required": ["register"]}})
    runs = [
        _run(miss, BAD, BAD),
        _run(_case("b", expect={"tools": {"forbidden": ["delete"]}}), _obs("delete")),
    ]
    s = summarize(runs)
    assert s.failure_pareto == (("missing_tool", 2), ("wrong_tool", 1))
    assert summarize([_run(_case("c"), GOOD)]).failure_pareto == ()


def test_as_rows_flattens_values_and_only_lists_intervals_that_exist():
    s = summarize([_run(_case("a", expect=REGISTER), GOOD, BAD)])
    rows = dict(s.as_rows())
    assert rows["cases"] == 1 and rows["runs"] == 2
    assert rows["task_success_rate"] == 0.5 and "task_success_rate_ci_low" not in rows
    assert rows["pass_at_all"] == 0.0 and "pass_at_all_ci_low" in rows
    assert rows["tool_argument_items"] == 0.5 and rows["latency_p50_ms"] == 0


def test_invalid_inputs_are_rejected():
    case = _case("a")
    with pytest.raises(ValueError):
        summarize([])
    with pytest.raises(ValueError):
        CaseRun(case, (), ())
    with pytest.raises(ValueError):
        CaseRun(case, (score_case(case, GOOD, NONE),), (GOOD, GOOD))


def test_precision_and_recall_use_different_denominators():
    case = _case("a", expect={"tools": {"required": ["register", "notify"]}})
    s = summarize([_run(case, _obs("register"))])  # 부른 것은 1개(전부 기대함), 기대는 2개
    assert (s.tool_precision.k, s.tool_precision.n) == (1, 1)
    assert (s.tool_recall.k, s.tool_recall.n) == (1, 2)


def test_expected_tools_ignore_calls_of_other_stages():
    case = _case(
        "a",
        path="main",
        expect={
            "tools": {"required": ["ask_schedule"]},
            "calls": [{"tool": "register", "stage": "schedule", "args": []}],
        },
    )
    obs = Observation(
        calls=[
            ToolCall(stage="main", name="ask_schedule"),
            ToolCall(stage="schedule", name="register"),
        ]
    )
    s = summarize([_run(case, obs)])
    assert (s.tool_recall.k, s.tool_recall.n) == (1, 1)  # 하위 단계 호출은 기대 도구에 세지 않는다
    assert (s.tool_precision.k, s.tool_precision.n) == (1, 1)


def test_failure_pareto_breaks_ties_by_name():
    runs = [
        _run(_case("a", expect={"tools": {"required": ["register"]}}), BAD),
        _run(_case("b", expect={"tools": {"forbidden": ["delete"]}}), _obs("delete")),
    ]
    assert summarize(runs).failure_pareto == (("missing_tool", 1), ("wrong_tool", 1))


def test_failure_pareto_sorts_by_count_before_name():
    runs = [
        _run(_case("a", expect={"tools": {"required": ["register"]}}), BAD),
        _run(
            _case("b", expect={"tools": {"forbidden": ["delete"]}}), _obs("delete"), _obs("delete")
        ),
    ]
    assert summarize(runs).failure_pareto == (("wrong_tool", 2), ("missing_tool", 1))


def test_repeats_must_all_pass_for_case_level_tool_metrics():
    s = summarize([_run(_case("a", expect=REGISTER), GOOD, BAD)])
    assert (s.tool_selection.k, s.tool_selection.n) == (0, 1)
    assert (s.tool_argument_cases.k, s.tool_argument_cases.n) == (0, 1)
    assert (s.task_success_rate.k, s.task_success_rate.n) == (1, 2)
    assert (s.pass_at_all.k, s.pass_at_all.n) == (0, 1)


def test_efficiency_means_follow_each_run():
    runs = [_run(_case("a"), _obs(llm_calls=1, steps=2), _obs(llm_calls=3, steps=4))]
    eff = summarize(runs).efficiency
    assert eff.llm_calls_mean == 2.0 and eff.steps_mean == 3.0


def test_precision_counts_errored_calls_and_helper_tools_as_called():
    case = _case("a", expect=REGISTER)
    helper = _obs("register", "lookup")
    s = summarize([_run(case, helper)])
    assert (s.tool_precision.k, s.tool_precision.n) == (1, 2)
    assert (s.tool_recall.k, s.tool_recall.n) == (1, 1)
    errored = Observation(
        calls=[ToolCall(stage="schedule", name="register", args={"title": "치과"}, is_error=True)]
    )
    s = summarize([_run(case, errored)])
    assert (s.tool_precision.k, s.tool_precision.n) == (1, 1)


def test_inconsistent_inputs_are_rejected():
    a, b = _case("a"), _case("b")
    with pytest.raises(ValueError):
        CaseRun(a, (score_case(b, GOOD, NONE),), (GOOD,))
    with pytest.raises(ValueError):
        summarize([_run(a, GOOD), _run(a, GOOD)])
    with pytest.raises(ValueError):
        summarize([_run(a, GOOD), _run(_case("c", split="val"), GOOD)])
