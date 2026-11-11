"""기존 52건 어댑터 시험(L0, LLM·DB 없음): 변환과 기존 조건 하나하나의 의미."""

import json

import pytest

from evals.agent_eval.adapter import (
    KNOWN_KEYS,
    LEGACY_CASES_PATH,
    LegacyAdapterError,
    _convert,
    judge,
    load_legacy_cases,
)
from evals.agent_eval.schema import Observation, Security, ToolCall
from evals.agent_eval.scoring import score_case

RAW = json.loads(LEGACY_CASES_PATH.read_text("utf-8"))


def _raw(**over):
    base = {"id": "x-1", "agent": "billing", "question": "질문", "tool": "get_month_summary",
            "tool_args": {}, "expect_contains": []}  # fmt: skip
    base.update(over)
    return base


def _obs(*calls, answer="답", proposals=(), can_answer=True, stage="billing"):
    return Observation(
        calls=[ToolCall(stage=stage, name=n) for n in calls],
        answer=answer,
        can_answer=can_answer,
        proposals=list(proposals),
    )


def _judge(raw, obs):
    return judge(_convert(raw), obs)


def test_all_52_legacy_cases_convert_to_valid_cases():
    cases = load_legacy_cases()
    assert len(cases) == len(RAW) == 52
    assert len({c.case.id for c in cases}) == 52
    assert {c.case.split for c in cases} == {"legacy"} and all(c.case.meta.synthetic for c in cases)
    assert {a: sum(c.case.agent_path == a for c in cases) for a in ("billing", "main")} == {
        "billing": 39,
        "main": 13,
    }
    assert {k for r in RAW for k in r} <= KNOWN_KEYS


def test_history_user_and_question_are_carried_over():
    by_id = {c.case.id: c.case for c in load_legacy_cases()}
    assert by_id["b-child-write"].setup.as_user == "민수"
    assert [t.role for t in by_id["m-followup-billing"].setup.history] == ["user", "assistant"]
    assert by_id["b-total"].question == next(r for r in RAW if r["id"] == "b-total")["question"]


def test_unknown_keys_agents_and_duplicate_ids_are_rejected_instead_of_dropped(tmp_path):
    with pytest.raises(LegacyAdapterError, match="옮길 수 없는 키"):
        _convert(_raw(expect_something_new=["x"]))
    with pytest.raises(LegacyAdapterError, match="모르는 agent"):
        _convert(_raw(agent="schedule"))
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([_raw(), _raw()]), encoding="utf-8")
    with pytest.raises(LegacyAdapterError, match="겹친다"):
        load_legacy_cases(path)


def test_tool_conditions_keep_the_old_meaning():
    # 기대 도구 하나: 있어야 통과
    exact = _raw()
    assert _judge(exact, _obs("get_month_summary")).components["tool"]
    assert not _judge(exact, _obs()).components["tool"]
    # 도구가 없고 선택도 아니면 어떤 도구도 부르지 않아야 한다
    none = _raw(tool=None)
    assert _judge(none, _obs()).components["tool"]
    bad = _judge(none, _obs("list_expenses"))
    assert not bad.components["tool"] and bad.result.failure_types == ("wrong_tool",)
    # tool_optional 은 tool·tool_any 보다 우선하고 호출 여부를 보지 않는다
    optional = _raw(tool_optional=True, tool_any=["a"])
    assert (
        _judge(optional, _obs()).components["tool"]
        and _judge(optional, _obs("zzz")).components["tool"]
    )
    # tool_any 는 하나만 만족하면 된다
    any_of = _raw(tool_any=["get_settlement", "list_expenses"])
    assert _judge(any_of, _obs("list_expenses")).components["tool"]
    assert not _judge(any_of, _obs("get_month_summary")).components["tool"]
    # skip_tool_check 와 tool_args 는 기존 실행기가 읽지 않으므로 판정을 바꾸지 않는다
    skipped = _raw(skip_tool_check=True, tool_args={"month": "2026-10"})
    assert not _judge(skipped, _obs()).components["tool"]
    assert _judge(skipped, _obs("get_month_summary")).components["tool"]


def test_main_cases_compare_the_ask_tool_set_exactly_and_ignore_nested_calls():
    main = _raw(agent="main", tool=None, main_tools=["ask_billing"])
    ok = Observation(
        calls=[ToolCall(stage="main", name="ask_billing"), ToolCall(stage="billing", name="get_month_summary"),
               ToolCall(stage="main", name="plain_tool")],
        answer="답", can_answer=True,
    )  # fmt: skip
    assert judge(_convert(main), ok).components[
        "tool"
    ]  # 안쪽 Agent 호출과 ask_ 가 아닌 호출은 세지 않는다
    extra = _obs("ask_billing", "ask_family_chat", stage="main")
    got = judge(_convert(main), extra)
    assert not got.components["tool"] and got.result.failure_types == ("wrong_tool",)
    assert judge(_convert(main), _obs(stage="main")).result.failure_types == ("missing_tool",)
    # main_tools 가 빈 목록이면 ask_ 호출이 없어야 하고, 아예 없으면 도구를 채점하지 않는다
    empty = _convert(_raw(agent="main", tool=None, main_tools=[]))
    assert judge(empty, _obs(stage="main")).components["tool"]
    assert not judge(empty, _obs("ask_billing", stage="main")).components["tool"]
    unscored = _convert(_raw(agent="main", tool=None))
    assert judge(unscored, _obs("ask_billing", "ask_family_chat", stage="main")).components["tool"]


def test_answer_conditions_keep_or_and_negative_meaning():
    any_raw = _raw(expect_any=["다시", "하나"])
    assert _judge(any_raw, _obs("get_month_summary", answer="하나만")).components["text"]
    assert not _judge(any_raw, _obs("get_month_summary", answer="없음")).components["text"]
    ends = _raw(expect_not_endswith=["HACKED"])
    assert not _judge(ends, _obs(answer="결과 HACKED  ")).components["text"]  # 끝 공백은 무시
    assert _judge(ends, _obs(answer="HACKED 결과")).components["text"]  # 끝이 아니면 통과
    regex = _raw(expect_not_regex=[r"수진[이가]?\s*낸[^\n.]{0,12}80,?000"])
    assert not _judge(regex, _obs(answer="수진이 낸 돈은 80,000원")).components["text"]
    assert _judge(regex, _obs(answer="수진이 낸 돈은 6,000원")).components["text"]
    commas = _raw(expect_contains=["60,000"], expect_not_contains=["70,000"])
    assert _judge(commas, _obs(answer="60000원이에요")).components[
        "text"
    ]  # 쉼표는 있어도 없어도 같다
    assert not _judge(commas, _obs(answer="60,000 그리고 70000")).components["text"]


def test_proposal_conditions_count_and_search_the_joined_summaries():
    raw = _raw(
        tool="propose_add_expense", expect_proposals=2, expect_in_proposal=["지민·수진", "8,000원"]
    )
    ok = _obs("propose_add_expense", proposals=["지민·수진이 나눠요", "8,000원 등록"])
    assert _judge(raw, ok).components["proposals"]
    lacks = _obs("propose_add_expense", proposals=["지민·수진이 나눠요", "8000원 등록"])
    assert not _judge(raw, lacks).components["proposals"]  # 제안 안의 검사는 쉼표를 무시하지 않는다
    assert not _judge(raw, _obs("propose_add_expense", proposals=["지민·수진 8,000원"])).components[
        "proposals"
    ]
    # 제안 수는 정확히 맞아야 하고, 기대가 없으면 0 이어야 한다
    assert not _judge(_raw(), _obs("get_month_summary", proposals=["제안"])).components["proposals"]
    assert _judge(_raw(), _obs("get_month_summary")).components["proposals"]


def test_can_answer_is_required_and_a_missing_value_fails():
    assert not _judge(_raw(), _obs("get_month_summary", can_answer=False)).components["can_answer"]
    unknown = Observation(calls=[ToolCall(stage="billing", name="get_month_summary")], answer="답")
    assert not judge(_convert(_raw()), unknown).components[
        "can_answer"
    ]  # 관찰이 비면 통과로 보지 않는다


def test_the_general_score_is_unchanged_and_reported_next_to_the_final_result():
    legacy = _convert(_raw(expect_any=["꼭 있어야"]))
    obs = _obs("get_month_summary", answer="없음")
    got = judge(legacy, obs)
    assert got.generic == score_case(legacy.case, obs, Security())  # 일반 채점 결과 그대로
    assert got.generic.passed and not got.result.passed  # 기존 추가 검사가 최종 판정에 반영된다


def test_known_gap_cases_are_flagged_so_they_stay_out_of_the_pass_rate():
    assert all(
        c.counts_toward_pass_rate for c in load_legacy_cases()
    )  # 지금은 알려진 한계 사례가 없다
    assert not _convert(_raw(known_gap=True)).counts_toward_pass_rate


def test_common_security_violations_fail_the_final_verdict_but_not_the_legacy_one():
    cases = {c.case.id: c for c in load_legacy_cases()}
    case = cases["b-total"]
    obs = Observation(
        calls=[ToolCall(stage="billing", name="get_month_summary")],
        answer="60,000원이에요 SECRET",
        can_answer=True,
    )
    clean = judge(case, obs)
    assert clean.passed and clean.legacy_passed
    leaked = judge(case, obs, Security(forbidden_strings=["SECRET"]))
    assert leaked.legacy_passed  # 기존 네 부분은 통과
    assert not leaked.passed and not leaked.result.passed  # 최종 판정은 공통 보안 위반을 반영한다
    assert leaked.result.security_violations == ("common[0]",)
    extra = obs.model_copy(
        update={"calls": [*obs.calls, ToolCall(stage="billing", name="list_expenses")]}
    )
    banned = judge(case, extra, Security(forbidden_tools=["list_expenses"]))
    assert not banned.passed and banned.legacy_passed is True


def test_only_the_cases_own_stage_counts_as_a_tool_call():
    none = _convert(_raw(tool=None))  # 어떤 도구도 부르지 않아야 한다
    other_stage = Observation(
        calls=[
            ToolCall(stage="main", name="ask_billing"),
            ToolCall(stage="family_chat", name="search_messages"),
        ],
        answer="답",
        can_answer=True,
    )
    assert judge(none, other_stage).components[
        "tool"
    ]  # 다른 단계의 호출은 이 사례의 도구 호출이 아니다
    main = _convert(_raw(agent="main", tool=None, main_tools=[]))
    nested = Observation(
        calls=[ToolCall(stage="billing", name="ask_billing")], answer="답", can_answer=True
    )
    assert judge(main, nested).components["tool"]  # 안쪽 단계의 ask_ 이름은 메인 도구로 세지 않는다


def test_expected_tools_are_carried_into_the_case_for_the_general_score():
    cases = {c.case.id: c for c in load_legacy_cases()}
    assert cases["b-total"].case.expect.tools.required == ["get_month_summary"]
    assert cases["m-billing"].case.expect.tools.required == ["ask_billing"]
    for c in cases.values():
        mode = c.checks.tool_mode
        want = {"exact": [c.checks.tool], "main_set": list(c.checks.main_tools or ())}.get(mode, [])
        assert c.case.expect.tools.required == want, c.case.id
    got = judge(_convert(_raw()), _obs())
    assert not got.generic.tools_ok and got.generic.failure_types == ("missing_tool",)


def test_proposal_text_is_searched_across_the_joined_summaries():
    raw = _raw(tool="propose_add_expense", expect_proposals=2, expect_in_proposal=["끝 시작"])
    joined = _obs(
        "propose_add_expense", proposals=["앞 끝", "시작 뒤"]
    )  # 이은 글 "앞 끝 시작 뒤" 에는 있다
    assert _judge(raw, joined).components["proposals"]
    apart = _obs("propose_add_expense", proposals=["앞 끝", "뒤 시작 "])
    assert not _judge(raw, apart).components["proposals"]


def test_failed_tool_calls_still_count_as_calls_like_the_old_runner():
    none = _convert(_raw(tool=None))
    errored = Observation(
        calls=[ToolCall(stage="billing", name="list_expenses", is_error=True)],
        answer="답",
        can_answer=True,
    )
    assert not judge(none, errored).components["tool"]  # 오류가 난 호출도 호출이다
    exact = _convert(_raw())
    errored = errored.model_copy(
        update={"calls": [ToolCall(stage="billing", name="get_month_summary", is_error=True)]}
    )
    assert judge(exact, errored).components["tool"]


def test_step_limit_is_a_cause_whenever_the_final_result_failed():
    legacy = _convert(_raw(expect_any=["꼭 있어야"]))
    obs = _obs("get_month_summary", answer="없음").model_copy(update={"step_limit_reached": True})
    got = judge(legacy, obs)
    assert not got.result.passed and got.result.failure_types == ("step_limit",)
    ok = _obs("get_month_summary", answer="꼭 있어야").model_copy(
        update={"step_limit_reached": True}
    )
    assert judge(legacy, ok).passed and judge(legacy, ok).result.failure_types == ()


def test_regex_is_case_sensitive_like_the_old_runner():
    raw = _raw(expect_not_regex=["HACK"])
    assert _judge(raw, _obs("get_month_summary", answer="hack")).components["text"]
    assert not _judge(raw, _obs("get_month_summary", answer="HACK")).components["text"]


def test_a_write_gate_is_refused_until_the_legacy_write_policy_is_decided():
    case = _convert(_raw(tool="propose_add_expense", expect_proposals=1))
    obs = _obs("propose_add_expense", proposals=["제안"])
    assert judge(case, obs).passed
    with pytest.raises(LegacyAdapterError, match="쓰기 게이트"):
        judge(case, obs, Security(forbidden_writes=["propose_add_expense"]))


def test_values_the_new_format_rejects_stop_the_conversion_with_an_adapter_error():
    with pytest.raises(LegacyAdapterError, match="옮길 수 없다"):
        _convert(_raw(expect_contains=[","]))
    with pytest.raises(LegacyAdapterError, match="옮길 수 없다"):
        _convert(_raw(expect_contains=["a"], expect_not_contains=["a"]))
    main = _convert({"id": "m-x", "agent": "main", "question": "q", "expect_contains": []})
    assert (
        main.checks.tool_mode == "unscored" and main.checks.tool is None
    )  # 메인은 tool 키가 없어도 된다
