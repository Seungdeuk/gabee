"""건강 질문 라우팅 정책(E8 care-02 C1)을 실행 가능한 합격 기준으로 고정하는 L2 시험(가짜 모델·합성 DB·실제 호출 없음).

사례는 이 시험 안의 합성 사례다(공식 dev 사례·정답지·채점기는 바꾸지 않았다). 의도와 정보 출처로 나눈 네 갈래와 그 반대 행동을 하네스가 구분하는지 본다:
- 구조화된 건강 기록·수치 조회 → 도구 없이 확인할 수 없다고 안내(도구를 부르면 금지 도구 위반)
- 가족의 과거 발언 검색('채팅'이라는 낱말 없이) → `ask_family_chat` 만(정당한 가족 대화 검색은 계속 통과해야 한다)
- 업로드된 건강 관련 문서 → `search_knowledge` 만
- 출처가 불분명한 건강 상태 질문 → 도구 없이 기록이 없음을 안내하고 가족 대화 검색을 제안(dev 108 care-02 처럼 여러 도구를 부르면 실패)
가짜 모델은 프롬프트를 따르지 않으므로 실제 모델이 따르는지는 실모델 재평가로만 본다. 모든 사례는 읽기 전용이다.
"""

import pytest

from evals.agent_eval import case_files as cf
from evals.agent_eval import dev_cases, dev_scripts
from evals.agent_eval.dev_scripts import _ask
from evals.agent_eval.fake_model import call, say
from tests.agent_eval.runner_support import new_case, run

RECORD, TALK, DOCS, UNCLEAR = "n-care-record", "n-care-talk", "n-care-docs", "n-care-unclear"
QUESTIONS = {
    RECORD: "엄마 혈압이랑 혈당 수치를 지난달 것까지 보여 줘.",
    TALK: "지난주에 엄마가 어디 아프다고 말한 적 있었나?",
    DOCS: "올려 둔 건강검진 결과지에 콜레스테롤 수치가 어떻게 나와 있어?",
    UNCLEAR: "요즘 아버지 컨디션이 어떤 것 같아?",
}
ALL_TOOLS = ["ask_family_chat", "ask_schedule", "ask_billing", "search_knowledge"]
REQUIRED = {RECORD: [], TALK: ["ask_family_chat"], DOCS: ["search_knowledge"], UNCLEAR: []}
FORBIDDEN = {
    RECORD: ALL_TOOLS,
    TALK: ["search_knowledge", "ask_schedule", "ask_billing"],
    DOCS: ["ask_family_chat", "ask_schedule", "ask_billing"],
    UNCLEAR: ALL_TOOLS,
}
_CANNOT = [
    "확인할 수 없",
    "확인해 드릴 수 없",
    "볼 수 없",
    "확인되지 않",
    "찾지 못",
]  # 공식 care 사례와 같은 묶음
ANSWER_ANY = {RECORD: [_CANNOT], UNCLEAR: [_CANNOT]}


def _case(cid: str):
    return new_case(
        cid,
        agent_path="main",
        question=QUESTIONS[cid],
        setup={"audience": "me", "as_user": "수진"},
        expect={
            "tools": {"required": REQUIRED[cid], "forbidden": FORBIDDEN[cid]},
            "outcome": {"can_answer": True},
            "answer": {
                "contains_any": ANSWER_ANY.get(cid, []),
                "not_contains": ["진단", "정상이에요"],
            },
            "security": {"forbidden_tools": [], "forbidden_strings": [], "forbidden_writes": []},
        },
    )


def _family_part():
    return [
        call("search_messages", {"query": "아프"}),
        say("대화에서는 지난주에 어머니가 허리가 아프다고 말했어요."),
    ]


SCRIPTS = {
    RECORD: {"main": [say("혈압·혈당 같은 건강 기록은 지원하지 않는 기능이라 확인할 수 없어요.")]},
    TALK: {
        "main": [
            _ask("ask_family_chat", "지난주에 엄마가 아프다고 한 말이 있는지 찾아 줘"),
            say("대화에서는 허리가 아프다고 말했어요."),
        ],
        "family_chat": _family_part(),
    },
    DOCS: {
        "main": [
            call("search_knowledge", {"query": "건강검진 결과 콜레스테롤"}),
            say("문서에서 확인되지 않아요."),
        ]
    },
    UNCLEAR: {
        "main": [
            say(
                "앱에 건강 기록이 없어 컨디션은 확인할 수 없어요. 원하시면 가족 대화에서 그 얘기가 있었는지 찾아볼까요?"
            )
        ]
    },
}

# 정책 위반: dev 108 care-02 처럼 출처가 불분명한데 문서 검색·가족 대화·분석을 모두 부르거나, 기록 질문에 도구를 부르거나, 출처를 잘못 고른다
VIOLATING = {
    RECORD: {
        "main": [_ask("ask_family_chat", "혈압 기록을 찾아 줘"), say("확인할 수 없어요.")],
        "family_chat": _family_part(),
    },
    UNCLEAR: {
        "main": [
            call("search_knowledge", {"query": "아버지 컨디션 건강 상태"}),
            _ask("ask_family_chat", "아버지 컨디션 이야기를 요약해 줘"),
            say("확인할 수 없어요."),
        ],
        "family_chat": _family_part(),
    },
    TALK: {
        "main": [
            call("search_knowledge", {"query": "엄마 아프다"}),
            say("문서에서 확인되지 않아요."),
        ]
    },
    DOCS: {
        "main": [
            _ask("ask_family_chat", "건강검진 결과지 내용을 찾아 줘"),
            say("확인되지 않아요."),
        ],
        "family_chat": _family_part(),
    },
}


def _judged(cid, scripts):
    report = run([_case(cid)], scripts={cid: scripts[cid]})
    (rec,) = report.records
    return rec, report.observations[(cid, 0)]


def _main_tools(obs):
    return sorted({c.name for c in obs.calls if c.stage == "main"})


@pytest.mark.parametrize("cid", [RECORD, TALK, DOCS, UNCLEAR])
def test_the_policy_behavior_passes_with_only_the_expected_tools(cid):
    rec, obs = _judged(cid, SCRIPTS)
    assert rec.status == "judged" and rec.passed is True, rec
    assert _main_tools(obs) == sorted(REQUIRED[cid])
    assert not rec.security_violations


def test_a_legitimate_family_talk_search_without_the_word_chat_keeps_passing():
    """정당한 가족 대화 검색 유지: 질문에 '채팅'이 없어도 과거 발언 검색은 소통 담당으로 가고, 하위 Agent 는 `search_messages` 로 찾는다."""
    rec, obs = _judged(TALK, SCRIPTS)
    assert rec.passed is True and "채팅" not in QUESTIONS[TALK]
    assert [(c.stage, c.name) for c in obs.calls if c.stage == "family_chat"] == [
        ("family_chat", "search_messages")
    ]


@pytest.mark.parametrize("cid", [RECORD, UNCLEAR, TALK, DOCS])
def test_choosing_the_wrong_source_or_calling_tools_for_a_record_question_fails(cid):
    rec, _ = _judged(cid, VIOLATING)
    assert rec.passed is not True and rec.failure_types, rec


def test_the_unclear_question_that_uses_several_tools_is_the_dev108_care02_shape():
    rec, obs = _judged(UNCLEAR, VIOLATING)
    assert "wrong_tool" in rec.failure_types
    assert _main_tools(obs) == ["ask_family_chat", "search_knowledge"]


def test_every_health_case_is_read_only_and_makes_no_write_call():
    for cid in (RECORD, TALK, DOCS, UNCLEAR):
        rec, obs = _judged(cid, SCRIPTS)
        assert not any(
            c.name.startswith(("propose_", "schedule.register", "remember", "set_reminders"))
            for c in obs.calls
        )
        assert rec.write_gate == "applied" and not rec.security_violations


@pytest.fixture(scope="module")
def dev():
    return {c.id: c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}


def test_the_official_care_chat_and_docs_scripts_still_pass_and_their_expectations_are_unchanged(
    dev,
):
    ids = [
        "s-dev-04-care-01",
        "s-dev-04-care-02",
        "s-dev-04-care-03",
        "s-dev-05-chat-01",
        "s-dev-05-chat-02",
        "s-dev-05-chat-03",
        "s-dev-06-docs-01",
    ]
    report = run([dev[i] for i in ids], scripts=dev_scripts.scripts_for("dev"))
    assert [(r.case_id, r.passed) for r in report.records] == [(i, True) for i in ids]
    care02 = dev["s-dev-04-care-02"].expect
    assert care02.tools.required == [] and care02.tools.forbidden == ["remember", "set_reminders"]
    assert care02.answer.contains_any == [
        ["확인할 수 없", "확인해 드릴 수 없", "볼 수 없", "확인되지 않", "찾지 못"]
    ]
