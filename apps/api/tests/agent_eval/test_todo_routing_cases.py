"""할 일 조회 라우팅 정책(E8 compound-03)을 실행 가능한 합격 기준으로 고정하는 L2 시험(가짜 모델·합성 DB·실제 호출 없음).

사례는 이 시험 안의 합성 사례다(공식 dev 사례·정답지·채점기는 바꾸지 않았다). 정책 위반 대본이 하네스에서 실패로 잡히는지까지 본다:
- 가족 공동 할 일만 → `ask_family_chat` 만 (일정 담당까지 부르면 금지 도구 위반)
- 내 일정 탭 할 일만 → `ask_schedule` 만 (소통 담당까지 부르면 금지 도구 위반)
- 어느 목록인지 불분명 → 둘 다 (하나만 부르면 필수 도구 누락)
- 지출 + 할 일 복합 → 정산 + 소통 + 일정 모두
가짜 모델은 프롬프트를 따르지 않으므로 실제 모델이 이 기준을 지키는지는 실모델 재평가로만 본다. 모든 사례는 읽기 전용이고 쓰기 도구는 호출하지 않는다.
공식 `compound-03` 의 필수 도구(`ask_billing`, `ask_family_chat`)는 그대로이고, `ask_schedule` 을 더 부르면 Tool Precision 이 어떻게 달라지는지도 여기서 센다.
"""

import pytest

from evals.agent_eval import case_files as cf
from evals.agent_eval import dev_cases, dev_scripts, metrics
from evals.agent_eval.dev_scripts import _ask, _query
from evals.agent_eval.fake_model import ToolUse, call, round_of, say
from tests.agent_eval.runner_support import new_case, run

FAMILY, TAB, BOTH, MIXED = "n-todo-family", "n-todo-tab", "n-todo-both", "n-todo-mixed"
QUESTIONS = {
    FAMILY: "가족 공동 할 일 목록에 뭐가 남아 있어?",
    TAB: "내 일정 탭에 있는 할 일을 알려 줘",
    BOTH: "이번 주에 해야 할 일 알려 줘",
    MIXED: "이번 달 문구류 지출이랑 이번 주에 해야 할 일을 같이 알려 줘",
}
REQUIRED = {
    FAMILY: ["ask_family_chat"],
    TAB: ["ask_schedule"],
    BOTH: ["ask_family_chat", "ask_schedule"],
    MIXED: ["ask_billing", "ask_family_chat", "ask_schedule"],
}
FORBIDDEN = {
    FAMILY: ["ask_schedule", "ask_billing"],
    TAB: ["ask_family_chat", "ask_billing"],
    BOTH: ["ask_billing"],
    MIXED: [],
}


def _case(cid: str):
    return new_case(
        cid,
        agent_path="main",
        question=QUESTIONS[cid],
        setup={"audience": "me", "as_user": "지민"},
        expect={
            "tools": {"required": REQUIRED[cid], "forbidden": FORBIDDEN[cid]},
            "outcome": {"can_answer": True},
            "security": {"forbidden_tools": [], "forbidden_strings": [], "forbidden_writes": []},
        },
    )


def _family_part():
    return [call("list_todos", {}), say("가족 공동 할 일은 우유 사기, 학교 준비물 챙기기예요.")]


def _schedule_part():
    return [_query("일정 탭에는 이번 주 할 일이 없어요.")]


def _billing_part():
    return [call("list_expenses", {"month": "2026-11"}), say("11월 문구류 지출은 없어요.")]


def _script(cid, tools):
    """tools: 메인이 한 번에 부르는 담당 도구 이름들. 각 담당의 하위 대본을 붙인다."""
    asks = [ToolUse(t, {"question": QUESTIONS[cid]}) for t in tools]
    out = {
        "main": [
            round_of(*asks) if len(asks) > 1 else _ask(tools[0], QUESTIONS[cid]),
            say("확인했어요."),
        ]
    }
    if "ask_family_chat" in tools:
        out["family_chat"] = _family_part()
    if "ask_schedule" in tools:
        out["schedule"] = _schedule_part()
    if "ask_billing" in tools:
        out["billing"] = _billing_part()
    return {cid: out}


def _judged(cid, tools):
    report = run([_case(cid)], scripts=_script(cid, tools))
    (rec,) = report.records
    return rec, report.observations[(cid, 0)], report


def _called(obs):
    return sorted({c.name for c in obs.calls if c.stage == "main"})


# ---------- 정책대로의 행동은 통과한다 ----------
@pytest.mark.parametrize(
    "cid, tools",
    [
        (FAMILY, ["ask_family_chat"]),
        (TAB, ["ask_schedule"]),
        (BOTH, ["ask_family_chat", "ask_schedule"]),
        (MIXED, ["ask_billing", "ask_family_chat", "ask_schedule"]),
    ],
)
def test_the_policy_behavior_passes_with_only_the_expected_agents(cid, tools):
    rec, obs, _ = _judged(cid, tools)
    assert rec.status == "judged" and rec.passed is True, rec
    assert _called(obs) == sorted(tools)
    assert not rec.security_violations


# ---------- 정책을 어기면 실패로 잡힌다 ----------
def test_asking_the_schedule_agent_for_a_family_only_request_is_a_double_lookup_failure():
    rec, obs, _ = _judged(FAMILY, ["ask_family_chat", "ask_schedule"])
    assert rec.passed is not True and "wrong_tool" in rec.failure_types


def test_asking_the_family_chat_agent_for_a_tab_only_request_is_a_double_lookup_failure():
    rec, obs, _ = _judged(TAB, ["ask_family_chat", "ask_schedule"])
    assert rec.passed is not True and "wrong_tool" in rec.failure_types


@pytest.mark.parametrize("only", ["ask_schedule", "ask_family_chat"])
def test_checking_only_one_list_for_an_unspecified_request_misses_a_required_tool(only):
    """dev 108 compound-03 r2 의 모양: 어느 목록인지 불분명한데 하나만 확인한다."""
    rec, obs, _ = _judged(BOTH, [only])
    assert rec.passed is not True and "missing_tool" in rec.failure_types


def test_a_mixed_request_that_skips_the_schedule_agent_misses_a_required_tool():
    rec, _, _ = _judged(MIXED, ["ask_billing", "ask_family_chat"])
    assert rec.passed is not True and "missing_tool" in rec.failure_types


# ---------- 읽기 전용 ----------
def test_every_routing_case_is_read_only_and_makes_no_write_call():
    for cid, tools in (
        (FAMILY, ["ask_family_chat"]),
        (TAB, ["ask_schedule"]),
        (BOTH, ["ask_family_chat", "ask_schedule"]),
        (MIXED, ["ask_billing", "ask_family_chat", "ask_schedule"]),
    ):
        rec, obs, _ = _judged(cid, tools)
        assert not any(c.name.startswith(("propose_", "schedule.register")) for c in obs.calls)
        assert rec.write_gate == "applied" and not rec.security_violations


# ---------- 기존 사례와 공식 compound-03 ----------
@pytest.fixture(scope="module")
def dev():
    return {c.id: c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}


def test_the_official_compound03_expectation_is_unchanged(dev):
    case = dev["s-dev-07-compound-03"]
    assert case.expect.tools.required == ["ask_billing", "ask_family_chat"]
    assert case.expect.tools.forbidden == []
    assert (
        case.expect.tools.allowed == []
    )  # ask_schedule 은 허용 목록에도 없다(정확도 지표에 그대로 반영된다)


def test_official_scripts_of_compound03_chat03_and_isolation03_still_pass(dev):
    ids = ["s-dev-07-compound-03", "s-dev-05-chat-03", "s-dev-10-isolation-03"]
    scripts = dev_scripts.scripts_for("dev")
    report = run([dev[i] for i in ids], scripts=scripts)
    assert [(r.case_id, r.passed) for r in report.records] == [(i, True) for i in ids]


def test_adding_ask_schedule_to_compound03_lowers_tool_precision_but_not_recall(dev):
    """정책 B 의 비용: 공식 필수 도구는 ask_billing·ask_family_chat 뿐이라 ask_schedule 호출은 필수가 아닌 호출(정밀도 분모)로 센다. 지표를 바꾸지 않고 영향만 잰다."""
    case = dev["s-dev-07-compound-03"]
    official = dev_scripts.scripts_for("dev")["s-dev-07-compound-03"]
    three = {
        "main": [
            round_of(
                ToolUse("ask_billing", {"question": "이번 달(2026년 11월) 장보기 지출을 알려 줘"}),
                ToolUse("ask_family_chat", {"question": "오늘 해야 할 할 일을 알려 줘"}),
                ToolUse("ask_schedule", {"question": "오늘 일정 탭의 할 일을 알려 줘"}),
            ),
            say("11월에는 장보기 지출이 없고, 오늘(11월 10일)이 기한인 할 일도 없어요."),
        ],
        "billing": official["billing"],
        "family_chat": official["family_chat"],
        "schedule": _schedule_part(),
    }
    a = run([case], scripts={case.id: official})
    b = run([case], scripts={case.id: three})
    obs_a, obs_b = a.observations[(case.id, 0)], b.observations[(case.id, 0)]
    expected = metrics._expected_tools(case)
    tools_a, tools_b = metrics._toolset(case, obs_a), metrics._toolset(case, obs_b)

    def precision(called):
        return len(called & expected) / len(called)

    assert precision(tools_a) == 1.0 and len(tools_a & expected) == len(expected)
    assert precision(tools_b) == pytest.approx(
        len(expected) / len(tools_b)
    )  # 필수 도구는 모두 불렀지만 정밀도는 내려간다
    assert precision(tools_b) < precision(tools_a) and (tools_b & expected) == expected
    assert b.records[0].passed is True  # 필수 도구를 모두 불렀으므로 공식 판정은 그대로 통과
    assert b.records[0].llm_calls > a.records[0].llm_calls  # 호출 수(비용)는 늘어난다
