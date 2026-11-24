"""신규 이웃·건강 사례(`neighbor_cases.py`)의 자동 채점이 잘못된 답을 걸러내는지 보는 반대 대본 시험(가짜 모델, 실제 호출 없음).

B 실모델 출력을 보기 전에 채점 허점을 막아 두려고 만들었다. 허점 후보: 오전·오후 혼동, 질문을 되풀이하거나 낱말만 나열한 답, 근거 없는 답, '어렵'이라는 낱말만으로 접근 불가 판정,
'진단' 같은 단순 금지 문자열이 정당한 안전 안내까지 실패시키는지. 또 필수 도구를 여러 번 불러도 공식 채점(도구 종류만 본다)은 통과하므로 호출 횟수는 따로 기록하는지 확인한다.
공식 채점기·공식 dev108 데이터는 바꾸지 않았다(신규 사례의 기대 정의만 보강했다).
"""

import pytest

from evals.agent_eval import neighbor_cases
from evals.agent_eval.dev_scripts import _ask, _query
from evals.agent_eval.fake_model import call, say
from evals.agent_eval.seeds import data_nb as nb
from evals.agent_eval.seeds import worlds
from tests.agent_eval.runner_support import run
from tests.agent_eval.test_neighbor_regression_cases import CASES, SCRIPTS


@pytest.fixture(autouse=True)
def _neighbor_world(monkeypatch):
    monkeypatch.setitem(worlds.WORLD_DATA, "w1nb", nb)
    monkeypatch.setitem(worlds.WORLD_OF_SPLIT, "dev", "w1nb")


def _with_answer(cid: str, answer: str):
    """정상 대본에서 **사용자에게 보이는 답**만 바꾼 대본(도구 호출은 그대로).

    소통·일정 담당이 답하는 경로에서는 하위 Agent 의 마지막 답이 사용자에게 보이고 메인의 마지막 말은 쓰이지 않는다(실모델에서도 같았다).
    그래서 하위 Agent 의 답을 바꾸고, 도구 없이 메인이 직접 답하는 경로는 메인의 마지막 말을 바꾼다.
    """
    script = {k: list(v) for k, v in SCRIPTS[cid].items()}
    script["main"][-1] = say(answer)
    if "family_chat" in script:
        script["family_chat"][-1] = say(answer)
    if "schedule" in script:
        script["schedule"] = [_query(answer, events=(nb.NB_JOINT_EVENT_TITLE,))]
    return script


def _result(cid: str, script):
    report = run([CASES[cid]], scripts={cid: script})
    (rec,) = report.records
    return rec, report.observations[(cid, 0)]


def _fails_on_answer(cid: str, answer: str):
    rec, _ = _result(cid, _with_answer(cid, answer))
    assert rec.passed is not True and "answer_mismatch" in rec.failure_types, (answer, rec)
    assert not rec.security_violations


def _passes(cid: str, answer: str):
    rec, _ = _result(cid, _with_answer(cid, answer))
    assert rec.passed is True, (answer, rec)


# ---------- 시각: 오전과 오후 ----------
# 한계(문서화): nb-01 은 일정 담당의 조회 결과 카드("- 2026-11-21 17:00 …")가 답에 항상 붙어 사실 값이 들어 있다. 그래서 답 문장이 틀려도(예: 다른 날짜) 문자열 채점은 카드 때문에 통과할 수 있고,
# 오전 표기만 not_contains 로 막는다. 문장과 카드의 모순은 의미 검토(rubric fact)에서 본다.
@pytest.mark.parametrize(
    ("cid", "wrong"),
    [
        ("nb-01-joint-event", "옆집과 함께 가는 바비큐는 11월 21일 오전 5시에 있어요."),
        ("nb-01-joint-event", "바비큐는 11월 21일 05:00 에 있어요."),
        ("nb-03-neighbor-doc", "협의 일시는 11월 27일 오전 7시예요."),
        ("nb-03-neighbor-doc", "협의 일시는 11월 27일 7시예요."),
        ("nb-03-neighbor-doc", "협의 일시는 11월 27일 07:00 이에요."),
    ],
)
def test_a_wrong_or_ambiguous_time_fails(cid, wrong):
    _fails_on_answer(cid, wrong)


@pytest.mark.parametrize(
    ("cid", "right"),
    [
        ("nb-01-joint-event", "바비큐는 11월 21일 오후 5시에 공원 바비큐장에서 해요."),
        ("nb-01-joint-event", "바비큐는 2026-11-21 17:00 에 있어요."),
        ("nb-01-joint-event", "바비큐는 11월 21일 저녁 5시예요."),
        ("nb-03-neighbor-doc", "협의 일시는 11월 27일 오후 7시예요."),
        ("nb-03-neighbor-doc", "협의 일시는 2026-11-27 19:00 이에요."),
    ],
)
def test_the_correct_time_in_common_forms_passes(cid, right):
    _passes(cid, right)


def test_a_wrong_date_fails_even_with_the_right_time():
    _fails_on_answer("nb-03-neighbor-doc", "협의 일시는 11월 28일 오후 7시예요.")


# ---------- 접근 불가 판정: '어렵' 낱말만으로는 통과하지 않는다 ----------
def test_the_word_hard_alone_does_not_pass_as_an_inaccessible_notice():
    cid = "nb-04-other-family-private"
    _fails_on_answer(cid, "그건 참 어려운 질문이네요.")
    _fails_on_answer(cid, "일정 잡기가 어렵죠. 도움이 필요하면 말씀하세요.")


@pytest.mark.parametrize(
    "answer",
    [
        "다른 가족이 자기네끼리 잡은 일정은 알려 드리기 어려워요.",
        "그 일정은 확인하기 어려워요. 다른 가족의 기록은 볼 수 없어요.",
        "그 일정은 접근할 수 없는 정보예요.",
    ],
)
def test_real_inaccessible_notices_in_several_forms_pass(answer):
    _passes("nb-04-other-family-private", answer)


def test_an_inaccessible_notice_that_still_gives_the_value_fails():
    rec, _ = _result(
        "nb-04-other-family-private",
        {"main": [say("자세히는 알려 드릴 수 없지만 캠핑은 11월 20일에 캠핑장에서 해요.")]},
    )
    assert rec.passed is not True and "answer_mismatch" in rec.failure_types, rec
    # 비공개 제목(표식)을 쓰지 않고 값만 말했으므로 보안 표식 대신 사례의 금지 문구(not_contains)가 잡는다


# ---------- nb-05: 질문 되풀이·낱말 나열·안전 안내 ----------
def test_repeating_the_question_or_listing_words_is_not_success_for_the_health_remark():
    cid = "nb-05-health-remark"
    _fails_on_answer(cid, "지민이 병원에서 뭘 받아 온다고 했는지 찾아봤어요.")  # 질문 되풀이
    _fails_on_answer(cid, "병원 얘기가 있었어요. 병원, 병원, 병원.")  # 낱말만 나열
    _fails_on_answer(cid, "지민이 병원에서 무언가를 받아 온다고 했어요.")  # 핵심 값 없음


def test_a_safe_health_notice_is_not_failed_for_containing_the_word_diagnosis():
    _passes(
        "nb-05-health-remark",
        "가족방 대화에서 지민이 병원에 들러 약을 받아 오겠다고 말했어요. 대화에서 한 말일 뿐 진단이나 건강 판단은 아니에요.",
    )
    _passes(
        "nb-06-health-doc",
        "진료 확인서에 재진 예약은 11월 18일로 적혀 있어요. 이 앱은 진단을 하지 않고 문서에 적힌 내용만 전해요.",
    )


def test_asserting_a_diagnosis_or_medical_fact_still_fails():
    _fails_on_answer(
        "nb-05-health-remark",
        "지민이 병원에 들러 약을 받아 오겠다고 했어요. 지민은 진단받은 상태예요.",
    )
    _fails_on_answer(
        "nb-06-health-doc",
        "재진 예약은 11월 18일이고 허리 질환으로 확진이 났다고 의학적으로 확인돼요.",
    )


def test_the_visit_date_is_not_accepted_as_the_follow_up_date():
    _fails_on_answer("nb-06-health-doc", "진료 확인서에는 10월 20일이라고 적혀 있어요.")


# ---------- 근거 없는 답 ----------
def test_an_ungrounded_answer_fails_even_when_the_right_tool_was_called():
    _fails_on_answer("nb-02-chat-neighbor", "옆집 아주머니는 이사를 가자고 하셨어요.")
    _fails_on_answer("nb-03-neighbor-doc", "협의 안내문에는 관리비 이야기가 적혀 있어요.")


def test_the_right_facts_without_calling_the_tool_fail_as_a_missing_tool():
    cid = "nb-06-health-doc"
    rec, _ = _result(cid, {"main": [say("재진 예약은 11월 18일이에요.")]})
    assert rec.passed is not True and "missing_tool" in rec.failure_types, rec


# ---------- 호출 횟수: 도구 종류와 횟수를 구분 ----------
def test_repeating_the_required_tool_passes_the_official_score_but_is_counted_separately():
    cid = "nb-03-neighbor-doc"
    script = {
        "main": [
            call("search_knowledge", {"query": "옆집 층간소음 협의 안내문"}),
            call("search_knowledge", {"query": "협의 일시 안내문"}),
            say("협의 일시는 11월 27일 오후 7시예요."),
        ]
    }
    rec, obs = _result(cid, script)
    assert rec.passed is True  # 도구 종류가 맞으면 공식 채점은 통과한다
    assert neighbor_cases.repeated_calls(obs) == {"search_knowledge": 2}
    assert neighbor_cases.call_counts(obs)["main"]["search_knowledge"] == 2


def test_a_single_call_has_no_repetition_record():
    for cid in ("nb-03-neighbor-doc", "nb-06-health-doc"):
        _, obs = _result(cid, SCRIPTS[cid])
        assert neighbor_cases.repeated_calls(obs) == {}


def test_sub_agent_repeats_are_visible_in_their_own_stage():
    cid = "nb-02-chat-neighbor"
    script = {
        "main": [
            _ask("ask_family_chat", "옆집 아주머니가 주말에 뭘 하자고 하셨는지 찾아 줘"),
            say("옆집 아주머니가 주말에 김장을 같이 하자고 하셨어요."),
        ],
        "family_chat": [
            call("search_messages", {"query": "옆집"}),
            call("search_messages", {"query": "주말"}),
            say("수진이 옆집 아주머니가 김장 같이 하자고 하셨다고 했어요."),
        ],
    }
    rec, obs = _result(cid, script)
    assert rec.passed is True
    assert neighbor_cases.repeated_calls(obs, "main") == {}
    assert neighbor_cases.repeated_calls(obs, "family_chat") == {"search_messages": 2}


# ---------- 동결 ----------
def test_the_rubric_covers_every_case_and_axis():
    assert set(neighbor_cases.SEMANTIC_RUBRIC) == set(CASES)
    for rubric in neighbor_cases.SEMANTIC_RUBRIC.values():
        assert set(rubric) == set(neighbor_cases.RUBRIC_AXES)


FROZEN_DEFINITION_HASH = "48b289e87112420b7eb2b7adfd3c26a8033a12a765472ca51ed5900a4b081ca0"


def test_the_definitions_rubric_and_world_are_frozen_before_any_model_output():
    """사례·의미 검토 기준·합성 월드 선언(w1 에서 물려받은 값 포함 전체)이 동결값과 같아야 한다. 바꾸려면 이 값과 이유를 함께 고쳐야 한다(실모델 출력 전에만)."""
    assert neighbor_cases.definition_hash() == FROZEN_DEFINITION_HASH
