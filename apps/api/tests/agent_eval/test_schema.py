"""평가 사례 스키마 시험(L0). 사례 파일을 불러올 때 잘못된 형식이 바로 걸러지는지 본다."""

import pytest
from pydantic import ValidationError

from evals.agent_eval.schema import Case, Observation, ToolCall


def _case(**over):
    base = {
        "id": "c-1",
        "split": "dev",
        "category": "C",
        "scenario": "single_tool",
        "agent_path": "schedule",
        "question": "내일 일정 알려줘",
        "meta": {"synthetic": True},
    }
    base.update(over)
    return base


def _call(**matcher):
    return {"expect": {"calls": [{"tool": "register", "args": [{"arg": "date", **matcher}]}]}}


def test_minimal_case_gets_defaults():
    case = Case.model_validate(_case())
    assert case.setup.audience == "me"
    assert case.expect.tools.required == [] and case.expect.calls == []
    assert case.expect.security.forbidden_writes == []


def test_defaults_are_not_shared_between_cases():
    a, b = Case.model_validate(_case()), Case.model_validate(_case())
    a.expect.tools.required.append("x")
    assert b.expect.tools.required == []


def test_scenario_is_required_except_for_legacy():
    with pytest.raises(ValidationError):
        Case.model_validate(_case(scenario=None))
    assert Case.model_validate(_case(split="legacy", scenario=None)).scenario is None


@pytest.mark.parametrize("synthetic", [False, 1, 1.0, "true", None])
def test_only_synthetic_cases_are_accepted(synthetic):
    with pytest.raises(ValidationError):
        Case.model_validate(_case(meta={"synthetic": synthetic}))


@pytest.mark.parametrize(
    "over",
    [
        {"split": "validation"},
        {"category": "Z"},
        {"scenario": "paraphrase"},
        {"agent_path": "rag"},
        {"unknown_field": 1},
        {"id": ""},
        {"id": "   "},
        {"question": ""},
        {"setup": {"history": [{"role": "system", "text": "x"}]}},
        {"setup": {"history": [{"role": "user", "text": ""}]}},
        {"setup": {"room": ""}},
        {"expect": {"tools": {"required": [""]}}},
        {"expect": {"tools": {"forbidden": [" "]}}},
        {"expect": {"calls": [{"tool": "", "args": []}]}},
        {"expect": {"calls": [{"tool": "t", "args": [{"arg": "", "match": "eq", "value": 1}]}]}},
        {"expect": {"outcome": {"proposals": -1}}},
        {"expect": {"outcome": {"proposals": True}}},
        {"expect": {"outcome": {"proposals": "2"}}},
        {"expect": {"outcome": {"can_answer": "yes"}}},
        {"expect": {"outcome": {"card_kind": ""}}},
        {"expect": {"answer": {"contains": [""]}}},
        {"expect": {"answer": {"not_contains": [","]}}},
        {"expect": {"answer": {"contains": ["  "]}}},
        {"expect": {"security": {"forbidden_strings": [""]}}},
        {"expect": {"security": {"forbidden_strings": [", ,"]}}},
        {"expect": {"security": {"check_args_of": [""]}}},
    ],
)
def test_unknown_values_empty_values_and_loose_types_are_rejected(over):
    with pytest.raises(ValidationError):
        Case.model_validate(_case(**over))


@pytest.mark.parametrize(
    "matcher",
    [
        {"match": "regex", "value": "("},
        {"match": "regex", "value": "a{99999999999999999999}"},
        {"match": "regex", "value": "(" * 5000 + "a" + ")" * 5000},
        {"match": "regex", "value": ""},
        {"match": "regex", "value": 123},
        {"match": "contains", "value": None},
        {"match": "contains", "value": ","},
        {"match": "contains", "value": "  "},
        {"match": "eq", "value": None},
        {"match": "eq", "value": float("nan")},
        {"match": "eq", "value": [1]},
        {"match": "date_range", "value": "2026-10"},
        {"match": "date_range", "value": {"from": "2026-10-31", "to": "2026-10-01"}},
        {"match": "date_range", "value": {"from": 20261001, "to": "2026-12-01"}},
        {"match": "date_range", "value": {"from": "20261001", "to": "2026-12-01"}},
        {"match": "date_range", "value": {"from": "2026-13-01", "to": "2026-12-01"}},
        {"match": "date_range", "value": {"from": "2026-10-01", "to": "2026-12-01", "x": "y"}},
        {"match": "any_of", "value": "me"},
        {"match": "any_of", "value": []},
        {"match": "any_of", "value": [[1]]},
        {"match": "any_of", "value": [None]},
        {"match": "any_of", "value": [float("inf")]},
    ],
)
def test_bad_matcher_values_are_rejected_when_loading(matcher):
    with pytest.raises(ValidationError):
        Case.model_validate(_case(**_call(**matcher)))


@pytest.mark.parametrize(
    "matcher",
    [
        {"match": "eq", "value": "2026-10-05"},
        {"match": "eq", "value": 60000},
        {"match": "eq", "value": True},
        {"match": "contains", "value": "치과"},
        {"match": "regex", "value": r"^\d{2}:\d{2}$"},
        {"match": "date_range", "value": {"from": "2026-10-01", "to": "2026-10-31"}},
        {"match": "date_range", "value": {"from": "2026-10-05", "to": "2026-10-05"}},
        {"match": "any_of", "value": ["me", 1, 2.5, True]},
    ],
)
def test_valid_matcher_values_are_accepted(matcher):
    case = Case.model_validate(_case(**_call(**matcher)))
    assert case.expect.calls[0].args[0].match == matcher["match"]


@pytest.mark.parametrize(
    "expect",
    [
        {"tools": {"required": ["register"], "forbidden": ["register"]}},
        {"tools": {"required": ["register"]}, "security": {"forbidden_tools": ["register"]}},
        {"tools": {"required": ["register"]}, "security": {"forbidden_writes": ["register"]}},
        {"calls": [{"tool": "register"}], "tools": {"forbidden": ["register"]}},
        {"calls": [{"tool": "register"}], "security": {"forbidden_tools": ["register"]}},
        {"calls": [{"tool": "register"}], "security": {"forbidden_writes": ["register"]}},
        {"answer": {"contains": ["등록"], "not_contains": ["등록"]}},
        {"answer": {"contains": ["김철수"]}, "security": {"forbidden_strings": ["김철수"]}},
    ],
)
def test_contradicting_cases_are_rejected(expect):
    with pytest.raises(ValidationError):
        Case.model_validate(_case(expect=expect))


def test_expected_call_may_name_a_stage_and_repeat_a_tool():
    case = Case.model_validate(
        _case(
            expect={
                "calls": [
                    {"tool": "register", "stage": "schedule", "args": []},
                    {"tool": "register", "stage": "schedule", "args": []},
                ]
            }
        )
    )
    assert [c.stage for c in case.expect.calls] == ["schedule", "schedule"]


def test_observation_defaults_and_validation():
    obs = Observation()
    assert obs.can_answer is None and obs.calls == []
    assert not obs.step_limit_reached and not obs.forced_final
    call = ToolCall(stage="main", name="ask_schedule")
    assert call.is_error is False and call.superseded is False
    with pytest.raises(ValidationError):
        Observation(steps=-1)
    with pytest.raises(ValidationError):
        Observation(tokens_in="5")
    with pytest.raises(ValidationError):
        Observation(unknown=1)
    with pytest.raises(ValidationError):
        ToolCall(stage="rag", name="x")
    with pytest.raises(ValidationError):
        ToolCall(stage="main", name="")
