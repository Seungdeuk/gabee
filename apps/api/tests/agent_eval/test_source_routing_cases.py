"""출처 판별(Main Agent 이중 호출 개선)을 실행 가능한 허용·금지 호출 기준으로 고정하는 L2 시험(가짜 모델·합성 DB·실제 호출 없음).

사례는 이 시험 안의 합성 사례다(공식 dev 사례·정답지·채점기는 바꾸지 않았다). 가짜 모델은 프롬프트를 따르지 않으므로 **실제 모델이 따르는지는 실모델 평가로만** 본다.
여기서는 (1) 정책대로의 호출 집합이 통과하고, (2) 출처가 분명한데 다른 담당까지 부르면(이중 호출) 하네스가 실패로 잡으며, (3) 공식 사례의 기대 도구는 그대로이고
추가 호출이 공식 판정(Task Success)과 호출 효율 지표(호출 수·Tool Precision)에 각각 어떻게 나타나는지를 분리해서 본다.

정책(2026-11-25 확정):
1. 가족방 대화·가족 공동 할 일 → `ask_family_chat` 만  2. 일정 탭의 일정·할 일 → `ask_schedule` 만
3. 출처가 실제로 불분명한 일반 할 일 → 둘 다(#535 compound-03)  4. 명확한 복합 → 실제로 필요한 담당만
5. 가족 채팅에서 뽑힌 약속·할 일 후보는 일정 탭 조회와 구분  6. 문서 검색·정산 라우팅은 그대로
"""

import pytest

from evals.agent_eval import case_files as cf
from evals.agent_eval import dev_cases, dev_scripts, metrics
from evals.agent_eval.dev_scripts import _ask, _query
from evals.agent_eval.fake_model import ToolUse, call, round_of, say
from tests.agent_eval.runner_support import new_case, run

ME = {"audience": "me", "as_user": "지민"}
ROOM = {"audience": "room", "room": "family", "as_user": "지민"}
# id -> (질문, 방 여부, 필수 담당, 금지 담당)
SPEC = {
    "n-src-family-todo": ("가족 공동 할 일 목록에 뭐가 남아 있어?", False, ["ask_family_chat"], ["ask_schedule", "ask_billing"]),
    "n-src-tab-only": ("내 일정 탭에 입력된 이번 주 일정을 알려 줘", False, ["ask_schedule"], ["ask_family_chat", "ask_billing"]),
    "n-src-tab-time": ("일정 탭에 있는 치과 진료가 몇 시에 시작하는지 알려 줘", False, ["ask_schedule"], ["ask_family_chat"]),
    "n-src-chat-search": ("가족 단체 채팅에서 지난 주말에 나눈 이야기를 찾아 줘", False, ["ask_family_chat"], ["ask_schedule"]),
    "n-src-chat-candidates": ("채팅 대화에서 정해진 약속 후보를 정리해 줘", False, ["ask_family_chat"], ["ask_schedule"]),
    "n-src-room-todo": ("@가비 남은 할 일 목록이 뭐였지?", True, ["ask_family_chat"], ["ask_schedule"]),
    "n-src-room-tab": ("@가비 일정 탭에 잡힌 공동 일정이 뭐야?", True, ["ask_schedule"], ["ask_family_chat"]),
    "n-src-room-chat-search": ("@가비 가족 채팅에서 지난 주말에 나눈 이야기를 찾아 줘", True, ["ask_family_chat"], ["ask_schedule"]),
    "n-src-unclear-todo": ("이번 주에 해야 할 일 알려 줘", False, ["ask_family_chat", "ask_schedule"], ["ask_billing"]),
    "n-src-compound": ("가족 채팅에서 일요일 이야기를 찾아서 그날 일정 탭에 잡혀 있는지도 알려 줘", False, ["ask_family_chat", "ask_schedule"], ["ask_billing"]),
    "n-src-money": ("이번 달 문구류 지출을 알려 줘", False, ["ask_billing"], ["ask_family_chat", "ask_schedule"]),
}  # fmt: skip
POLICY_CALLS = {cid: list(spec[2]) for cid, spec in SPEC.items()}


def _case(cid):
    question, room, required, forbidden = SPEC[cid]
    return new_case(
        cid,
        agent_path="main",
        question=question,
        setup=ROOM if room else ME,
        expect={
            "tools": {"required": required, "forbidden": forbidden},
            "outcome": {"can_answer": True},
            "security": {"forbidden_tools": [], "forbidden_strings": [], "forbidden_writes": []},
        },
    )


def _script(cid, tools):
    question = SPEC[cid][0]
    asks = [ToolUse(t, {"question": question}) for t in tools]
    out = {
        "main": [round_of(*asks) if len(asks) > 1 else _ask(tools[0], question), say("확인했어요.")]
    }
    if "ask_family_chat" in tools:
        out["family_chat"] = [call("list_todos", {}), say("가족 대화와 공동 할 일을 확인했어요.")]
    if "ask_schedule" in tools:
        out["schedule"] = [_query("일정 탭을 확인했어요.")]
    if "ask_billing" in tools:
        out["billing"] = [call("list_expenses", {"month": "2026-11"}), say("지출을 확인했어요.")]
    return {cid: out}


def _judged(cid, tools):
    report = run([_case(cid)], scripts=_script(cid, tools))
    (rec,) = report.records
    return rec, report.observations[(cid, 0)]


def _called(obs):
    return sorted({c.name for c in obs.calls if c.stage == "main"})


@pytest.mark.parametrize("cid", sorted(SPEC))
def test_the_policy_call_set_passes_with_only_the_needed_agents(cid):
    rec, obs = _judged(cid, POLICY_CALLS[cid])
    assert rec.status == "judged" and rec.passed is True, rec
    assert _called(obs) == sorted(POLICY_CALLS[cid]) and not rec.security_violations


@pytest.mark.parametrize(
    "cid",
    [c for c in sorted(SPEC) if len(POLICY_CALLS[c]) == 1],
)
def test_adding_another_agent_to_a_single_source_request_is_caught_as_a_double_call(cid):
    """출처가 분명한 질문에서 다른 담당(소통↔일정)까지 부르면 금지 호출로 실패한다."""
    required = POLICY_CALLS[cid]
    extra = next(
        t
        for t in ("ask_schedule", "ask_family_chat", "ask_billing")
        if t not in required and t in SPEC[cid][3]
    )
    rec, obs = _judged(cid, [*required, extra])
    assert rec.passed is not True and "wrong_tool" in rec.failure_types
    assert _called(obs) == sorted([*required, extra])


@pytest.mark.parametrize("only", ["ask_family_chat", "ask_schedule"])
def test_an_unclear_todo_lookup_still_needs_both_lists(only):
    """#535 compound-03 의 효과 보존: 출처가 불분명한 일반 할 일 조회를 한쪽만 확인하면 필수 도구 누락이다."""
    rec, _ = _judged("n-src-unclear-todo", [only])
    assert rec.passed is not True and "missing_tool" in rec.failure_types


def test_an_explicit_compound_request_needs_exactly_the_two_requested_agents():
    rec, obs = _judged("n-src-compound", ["ask_family_chat"])
    assert rec.passed is not True and "missing_tool" in rec.failure_types
    rec, obs = _judged("n-src-compound", ["ask_family_chat", "ask_schedule", "ask_billing"])
    assert rec.passed is not True and "wrong_tool" in rec.failure_types  # 요청하지 않은 정산 담당


def test_every_routing_case_is_read_only():
    for cid in SPEC:
        rec, obs = _judged(cid, POLICY_CALLS[cid])
        assert not any(c.name.startswith(("propose_", "schedule.register")) for c in obs.calls)
        assert rec.write_gate == "applied" and not rec.security_violations


# ---------- 공식 사례: 기대 도구는 그대로, 추가 호출은 판정과 효율 지표에 따로 나타난다 ----------
OFFICIAL = {
    "s-dev-01-routing-02": ["ask_family_chat"],
    "s-dev-02-schedq-01": ["ask_schedule"],
    "s-dev-05-chat-02": ["ask_family_chat"],
    "s-dev-05-chat-03": ["ask_family_chat"],
    "s-dev-07-compound-03": ["ask_billing", "ask_family_chat"],
    "s-dev-04-care-02": [],  # 공식 필수 도구 없음(인접 기능 회귀: 소통·일정 외 호출 금지만 본다)
}


@pytest.fixture(scope="module")
def dev():
    return {c.id: c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}


def test_the_official_expectations_of_the_related_cases_are_unchanged(dev):
    assert dev["s-dev-01-routing-02"].expect.tools.required == ["ask_family_chat"]
    assert dev["s-dev-02-schedq-01"].expect.tools.required == ["schedule.query"]
    assert dev["s-dev-05-chat-02"].expect.tools.required == ["search_messages"]
    assert dev["s-dev-05-chat-03"].expect.tools.required == ["analyze_recent_chat", "list_todos"]
    assert dev["s-dev-07-compound-03"].expect.tools.required == ["ask_billing", "ask_family_chat"]
    assert dev["s-dev-07-compound-03"].expect.tools.allowed == []


def test_the_official_scripts_of_the_related_cases_still_pass_and_never_double_call(dev):
    scripts = dev_scripts.scripts_for("dev")
    ids = list(OFFICIAL)
    report = run([dev[i] for i in ids], scripts=scripts)
    assert [(r.case_id, r.passed) for r in report.records] == [(i, True) for i in ids]
    for cid in ids:
        main = {c.name for c in report.observations[(cid, 0)].calls if c.stage == "main"}
        assert not {"ask_family_chat", "ask_schedule"} <= main, (
            cid
        )  # 정상 대본에는 이중 호출이 없다


def test_an_extra_call_is_measured_separately_from_official_task_success(dev):
    """routing-02: 공식 정답지는 `ask_schedule` 을 금지하지 않아 Task Success 는 그대로지만, 호출 수는 늘고 Tool Precision 은 내려간다(호출 효율 지표)."""
    case = dev["s-dev-01-routing-02"]
    official = dev_scripts.scripts_for("dev")[case.id]
    q = case.question
    double = {
        "main": [
            round_of(
                ToolUse("ask_family_chat", {"question": q}),
                ToolUse("ask_schedule", {"question": q}),
            ),
            official["main"][-1],  # 같은 최종 답(공식 기대 문구 포함)
        ],
        "family_chat": official["family_chat"],
        "schedule": [_query("일정 탭을 확인했어요.")],
    }
    a = run([case], scripts={case.id: official})
    b = run([case], scripts={case.id: double})
    obs_a, obs_b = a.observations[(case.id, 0)], b.observations[(case.id, 0)]
    expected = metrics._expected_tools(case)
    tools_a, tools_b = metrics._toolset(case, obs_a), metrics._toolset(case, obs_b)
    assert a.records[0].passed is True and b.records[0].passed is True  # 공식 Task Success 는 같다
    assert (tools_a & expected) == expected and (tools_b & expected) == expected  # 재현율 같다
    assert len(tools_b & expected) / len(tools_b) < len(tools_a & expected) / len(
        tools_a
    )  # 정밀도는 내려간다
    assert b.records[0].llm_calls > a.records[0].llm_calls  # 호출 수(비용)는 늘어난다


# ---------- 질문 의미 보존: 담당을 맞게 골라도 질문을 바꿔 넘기면 하위 Agent 가 엉뚱한 도구를 쓴다 ----------
CHAT_LIST = "n-src-room-chat-list"
CHAT_LIST_Q = "@가비 대화에서 정한 목록이 뭐였지?"


def _chat_list_case():
    return new_case(
        CHAT_LIST,
        agent_path="family_chat",
        question=CHAT_LIST_Q,
        setup=ROOM,
        expect={
            # 소통 Agent 경로 사례는 하위 Agent 의 도구로 판정한다(공식 chat-02 와 같은 방식: 대화 검색이 필수)
            "tools": {"required": ["search_messages"], "forbidden": []},
            "outcome": {"can_answer": True},
            "security": {"forbidden_tools": [], "forbidden_strings": [], "forbidden_writes": []},
        },
    )


def _chat_list_script(handoff, sub_tool, sub_args):
    return {
        CHAT_LIST: {
            "main": [_ask("ask_family_chat", handoff), say("확인했어요.")],
            "family_chat": [call(sub_tool, sub_args), say("대화에서 정한 목록을 찾았어요.")],
        }
    }


def test_a_preserved_question_lets_the_chat_agent_search_the_conversation():
    """메인이 '대화에서 정한 목록' 이라는 대상·출처를 그대로 넘기면 소통 Agent 가 대화를 검색하고 통과한다."""
    report = run(
        [_chat_list_case()],
        scripts=_chat_list_script(
            "대화에서 정한 목록을 찾아 줘", "search_messages", {"query": "목록"}
        ),
    )
    (rec,) = report.records
    assert rec.passed is True, rec


def test_rewriting_the_question_into_registered_todos_makes_the_sub_agent_miss_the_search():
    """정책대로 소통 Agent 를 골랐어도 질문을 '공동 할 일 목록' 으로 바꿔 넘기면 하위 Agent 가 list_todos 만 써 필수 대화 검색이 빠진다(통합 평가 chat-02 r0 의 모양).
    가짜 모델이라 실제 모델이 질문을 바꾸는지는 알 수 없고, 하네스가 이 실패를 잡는지만 본다."""
    report = run(
        [_chat_list_case()],
        scripts=_chat_list_script("가족 공동 할 일 목록을 알려 줘", "list_todos", {}),
    )
    (rec,) = report.records
    assert rec.passed is not True and "missing_tool" in rec.failure_types


def test_the_official_chat02_script_hands_off_the_question_without_changing_its_target(dev):
    """공식 chat-02 정상 대본: 메인이 넘기는 질문이 사용자 질문의 대상(목록)을 유지하고 공동 할 일로 바꾸지 않으며, 소통 Agent 는 대화를 검색한다."""
    script = dev_scripts.scripts_for("dev")["s-dev-05-chat-02"]
    handoff = script["main"][0].tools[0].args["question"]
    assert "목록" in handoff and "공동 할 일" not in handoff
    assert script["family_chat"][0].tools[0].name == "search_messages"
    report = run([dev["s-dev-05-chat-02"]], scripts={"s-dev-05-chat-02": script})
    assert report.records[0].passed is True
