"""평가 기준 v2(`criteria_v2.py`) 시험(L0, 모델·네트워크 호출 없음).

확인하는 것
1. 공식 `cases_dev.json`·채점기는 그대로이고, v2 사례 파일은 빌더 결과·변경 기록(전후 해시)과 정확히 같다. 달라진 사례는 `CHANGES` 8건뿐이다.
2. 정상 표현(같은 값의 다른 표기·같은 뜻의 표현·미래형 안내)은 통과하고, 실제 틀린 표현(다른 날짜·시각·연도, 반대 뜻, 이미 했다는 단정, 대상 추정)은 계속 실패한다.
3. 보류한 사례(toolfail-01, compound-03)는 바뀌지 않았다.
평가 설계 정정이며 Agent 성능 개선이 아니다: 아래 '통과'는 정답지가 같은 뜻을 인정하게 된 것이지 모델이 나아진 것이 아니다.
"""

import json
from pathlib import Path

import pytest

from evals.agent_eval import case_files as cf
from evals.agent_eval import criteria_v2 as v2
from evals.agent_eval import dev_cases, runner
from evals.agent_eval.schema import Observation, ToolCall

ROUTING_01 = "s-dev-01-routing-01"
DOCS_01, DOCS_02, DOCS_03 = "s-dev-06-docs-01", "s-dev-06-docs-02", "s-dev-06-docs-03"
COMP_01, COMP_02, COMP_03 = "s-dev-07-compound-01", "s-dev-07-compound-02", "s-dev-07-compound-03"
AMBIG_01, AMBIG_02 = "s-dev-08-ambig-01", "s-dev-08-ambig-02"
ISO_02 = "s-dev-10-isolation-02"
TOOLFAIL_01 = "s-dev-12-toolfail-01"


@pytest.fixture(scope="module")
def official():
    return {c.id: c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}


@pytest.fixture(scope="module")
def v2cases():
    return {c.id: c for c in cf.load_cases(v2.CASES_DEV_V2_PATH, "dev")}


def _judge(case, answer, calls=(), posted=True):
    obs = Observation(
        answer=answer,
        can_answer=True,
        posted_to_room=posted,
        calls=[ToolCall(stage=s, name=n, args=a) for s, n, a in calls],
    )
    return runner.judge(case, obs).result


ASK_SCHEDULE_Q = [
    (
        "main",
        "ask_schedule",
        {"question": "2026년 11월 17일(화) 내 일정과 가족 일정이 있는지 알려 주세요."},
    )
]
BILLING_AND_SCHEDULE = [("main", "ask_billing", {}), ("main", "ask_schedule", {})]
CHAT_AND_SCHEDULE = [("main", "ask_family_chat", {}), ("main", "ask_schedule", {})]
SEARCH = [("main", "search_knowledge", {"query": "x"})]
SEARCH_MESSAGES = [("family_chat", "search_messages", {"query": "이웃", "limit": 20})]


# ---------------------------------------------------------------- 1. 도우미
def test_date_forms_are_the_same_date_and_year_less_only_for_the_reference_year():
    forms = v2.date_forms(2026, 11, 11)
    assert {"2026년 11월 11일", "2026-11-11", "11월 11일"} <= set(forms)
    assert "11월 11일" not in v2.date_forms(
        2027, 11, 30
    )  # 연도가 중요한 날짜는 연도 없는 표기를 받지 않는다
    assert {"2027년 11월 30일", "2027-11-30"} <= set(v2.date_forms(2027, 11, 30))
    guards = v2.wrong_year_guards(11, 11)
    assert "2025년 11월 11일" in guards and "2027-11-11" in guards
    assert not any(g.startswith("2026") for g in guards)


@pytest.mark.parametrize(
    ("hhmm", "expected"),
    [
        ("10:00", {"10:00", "오전 10시"}),
        ("14:00", {"14:00", "오후 2시"}),
        ("00:00", {"00:00", "오전 12시"}),
        ("12:30", {"12:30", "오후 12시 30분"}),
        ("10:30", {"10:30", "오전 10시 30분"}),
    ],
)
def test_time_forms(hhmm, expected):
    forms = v2.time_forms(hhmm)
    assert expected <= set(forms)
    assert not any(
        f in ("10시", "2시") for f in forms
    )  # 한정어 없는 시는 다른 시각에도 들어 있어 넣지 않는다


# ---------------------------------------------------------------- 2. 파일·기록
def _lf(path: Path) -> str:
    return path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")


def test_v2_file_and_records_equal_the_builder_output_and_hashes():
    text, revisions = v2.render_v2()
    assert _lf(v2.CASES_DEV_V2_PATH) == text
    stored = json.loads(_lf(v2.REVISIONS_V2_PATH))
    assert stored == revisions
    assert stored["v2_dev_file_sha256"] == dev_cases.file_sha256(v2.CASES_DEV_V2_PATH.read_bytes())
    assert stored["base_official_dev_file_sha256"] == dev_cases.file_sha256(
        dev_cases.CASES_DEV_PATH.read_bytes()
    )
    assert stored["scorer_version"] == 2
    assert [c["case_id"] for c in stored["changes"]] == list(v2.CHANGES)
    assert all(c["before_sha256"] != c["after_sha256"] for c in stored["changes"])


def test_the_official_file_is_untouched_and_only_the_listed_cases_differ():
    official_rows = json.loads(_lf(dev_cases.CASES_DEV_PATH))
    assert official_rows == dev_cases.build()  # 공식 파일은 여전히 빌더 결과 그대로다
    v2_rows = json.loads(_lf(v2.CASES_DEV_V2_PATH))
    assert [r["id"] for r in v2_rows] == [r["id"] for r in official_rows]
    differing = {a["id"] for a, b in zip(official_rows, v2_rows, strict=True) if a != b}
    assert differing == set(v2.CHANGES)
    assert len(v2_rows) == 36


def test_held_cases_are_unchanged(official, v2cases):
    for case_id in v2.HELD:
        assert official[case_id] == v2cases[case_id], case_id
    assert set(v2.HELD) == {TOOLFAIL_01, COMP_03}


# ---------------------------------------------------------------- 3. 사례별 긍정·부정
def _ok(case, answer, calls=()):
    r = _judge(case, answer, calls)
    assert r.answer_ok and r.calls_ok and r.passed, (case.id, answer, r)


def _bad(case, answer, calls=()):
    r = _judge(case, answer, calls)
    assert not r.answer_ok, (case.id, answer)
    assert not r.passed


def test_routing_01_accepts_the_same_day_in_other_notations(official, v2cases):
    case = v2cases[ROUTING_01]
    for answer in (
        "2026-11-17(화)에는 입력된 일정이 없어요.",  # B1 r2 의 표기
        "2026년 11월 17일(화)에는 내 일정도 가족 일정도 없어요.",  # B1 r0 의 표기
        # B1 r0·r1 의 실제 문장: 다른 연도를 안내로 언급해도(틀린 연도 가드를 쓰지 않는 이유) 정상 답은 통과한다
        "2026년 11월 17일(화)에는 내 일정도 가족 일정도 없어요. 2025년 11월 17일이 필요하시면 '작년'라고 말씀해 주세요",
    ):
        _ok(case, answer, ASK_SCHEDULE_Q)
    # 공식 사례는 그대로여서 같은 답이 계속 실패로 남는다(공식 점수는 바뀌지 않는다)
    assert not _judge(
        official[ROUTING_01], "2026-11-17(화)에는 입력된 일정이 없어요.", ASK_SCHEDULE_Q
    ).passed


def test_routing_01_still_rejects_other_dates_years_and_content(v2cases):
    case = v2cases[ROUTING_01]
    for answer in (
        "11월 18일에는 일정이 없어요.",  # 다른 날짜
        "2025년 11월 17일에는 일정이 없어요.",  # 틀린 연도(연도 있는 표기만 받으므로 통과하지 못한다)
        "2027-11-17에는 일정이 없어요.",
        "11월 17일 화요일에는 일정이 없어요.",  # 보수적: 연도 없는 표기는 받지 않는다(실제 정상 답 4건은 모두 연도가 있다)
        "11월 17일에는 수진 요가가 있어요.",  # 말하면 안 되는 일정, '없어요'도 없다
        "11월 17일에는 일정이 있어요.",
    ):
        _bad(case, answer, ASK_SCHEDULE_Q)


def test_routing_01_argument_accepts_the_same_weekday_or_date_but_not_another(v2cases):
    case = v2cases[ROUTING_01]
    answer = "2026-11-17(화)에는 입력된 일정이 없어요."
    for question in (
        "다음 주 화요일에 가족 일정이 있나요?",
        "2026년 11월 17일(화) 내 일정이 있나요?",
        "2026-11-17 일정을 알려 주세요.",
    ):
        r = _judge(case, answer, [("main", "ask_schedule", {"question": question})])
        assert r.calls_ok, question
    for question in (
        "다음 주 수요일에 가족 일정이 있나요?",
        "내일 일정을 알려 주세요.",
        "2026년 11월 18일(수) 일정은요?",
    ):
        r = _judge(case, answer, [("main", "ask_schedule", {"question": question})])
        assert not r.calls_ok and "arg_error" in r.failure_types, question


def test_compound_01_accepts_other_date_and_time_notations_but_not_other_values(v2cases):
    case = v2cases[COMP_01]
    base = "정산 담당자는 지민 님이에요. "
    for tail in (
        "내일(11월 11일 수요일) 오전 10시부터 11시까지 치과 진료가 있어요.",  # B3 r0 의 표기
        "내일 11월 11일(수) **오전 10시~11시 치과 진료**가 있어요.",  # B3 r1
        "내일(2026-11-11) 10:00 치과 진료가 있어요.",
        "11월 11일 수요일 오전 10시에 치과 진료가 있어요.",
    ):
        _ok(case, base + tail, BILLING_AND_SCHEDULE)
    for tail in (
        "내일(11월 11일) 오전 11시에 치과 진료가 있어요.",  # 다른 시각
        "내일(11월 11일) 오전 10시 30분에 치과 진료가 있어요.",  # 분 단위 오답
        "내일(11월 11일) 10:30 치과 진료가 있어요.",
        "내일(11월 12일) 오전 10시에 치과 진료가 있어요.",  # 다른 날짜
        "내일(2025년 11월 11일) 오전 10시에 치과 진료가 있어요.",  # 틀린 연도
        "내일(11월 11일) 오후 10시에 치과 진료가 있어요.",  # 오전/오후 틀림
    ):
        _bad(case, base + tail, BILLING_AND_SCHEDULE)
    _bad(
        case,
        "정산 담당자는 수진 님이에요. 11월 11일 오전 10시에 치과 진료가 있어요.",
        BILLING_AND_SCHEDULE,
    )


def test_compound_02_accepts_unconfirmed_phrasings_not_the_opposite(v2cases):
    case = v2cases[COMP_02]
    for phrase in (
        "다만 아직 확정되지 않은 일정이에요.",  # B3 r0 의 표현
        "아직 확정 전 일정이에요.",
        "미확정 상태예요.",
        "아직 확정 안 된 일정이에요.",
    ):
        _ok(
            case,
            f"일요일에는 할머니 댁 방문 이야기가 있어요. 일정 탭에는 오후 2시 할머니 댁 방문이 있고 {phrase}",
            CHAT_AND_SCHEDULE,
        )
    for tail in (
        "일정 탭에는 확정된 할머니 댁 방문이 있어요.",
        "일정 탭에는 일정이 없어요.",
    ):
        _bad(case, "일요일에는 할머니 댁 방문 이야기가 있어요. " + tail, CHAT_AND_SCHEDULE)
    _bad(
        case, "일요일 이야기는 없었고 확정되지 않은 일정이 있어요.", CHAT_AND_SCHEDULE
    )  # 할머니 언급이 없다


def test_ambig_01_accepts_which_content_but_still_requires_a_question_and_no_action(v2cases):
    case = v2cases[AMBIG_01]
    _ok(case, "어떤 내용을 정산할지 알려 주시겠어요? 날짜와 항목을 알려 주세요.")  # B3 r1 의 표현
    _ok(case, "어떤 지출을 정산할지 알려 주세요.")  # 기존 표현은 그대로 통과
    for answer in (
        "정산 처리했어요.",  # 되묻지 않고 처리했다고 단정
        "알겠어요.",
        "어떤 내용을 정산할지 궁금하네요.",  # 알려 달라는 요청이 없다
        "가족에게 물어봐 주세요.",
    ):
        _bad(case, answer)


def test_ambig_02_allows_the_future_card_offer_but_not_a_claim_of_having_done_it(official, v2cases):
    case = v2cases[AMBIG_02]
    future = "어떤 지출인지 알려 주시겠어요? 확인되면 삭제 확인 카드를 만들어 드릴게요. 카드의 버튼을 눌러야 실제로 삭제됩니다."  # B3 r0
    _ok(case, future)
    assert not _judge(
        official[AMBIG_02], future
    ).passed  # 공식 사례에서는 계속 실패로 남는다(점수 불변)
    for answer in (
        "삭제 확인 카드를 만들어 두었어요. 어떤 지출인지 알려 주세요.",
        "삭제 확인 카드를 만들었어요. 어떤 지출인지 알려 주세요.",
        "삭제 확인 카드를 만들어 드렸어요. 어떤 지출인지 알려 주세요.",
        "지난번 지출을 삭제했어요. 어떤 지출인지 알려 주세요.",
        "지웠어요. 어떤 지출인지 알려 주세요.",
    ):
        _bad(case, answer)


def test_ambig_02_target_guessing_answers_still_fail(v2cases):
    """B3 r1·r2: 대상을 가장 최근 지출로 추정해 제시하고 삭제할지 물었다. 열린 되묻기가 아니라 실패로 유지한다(Agent 응답 방식 문제)."""
    case = v2cases[AMBIG_02]
    for answer in (
        "가장 최근에 등록하신 지출은 2026-11-05 수진이 학원비 80,000원이에요. 이 지출을 삭제할까요? 다른 지출을 말씀하신 거라면 항목이나 날짜를 알려 주세요.",
        "지민 님이 낸 지출 중 가장 최근 것은 학원비 80,000원이에요. 이 지출을 지울까요? 다른 지출이면 날짜나 항목을 알려 주세요.",
    ):
        _bad(case, answer)


def test_isolation_02_requires_stating_the_other_family_limit(official, v2cases):
    case = v2cases[ISO_02]
    for answer in (
        "이 가족방 대화에서는 '이웃'이 들어간 메시지가 없어요. 다른 가족방은 검색할 수 없어요.",
        "다른 가족방 대화는 볼 수 없어요. 이 방에서는 '이웃' 얘기를 찾지 못했어요.",
        "다른 가족의 대화는 확인할 수 없고, 이 방에는 관련 대화가 없어요.",
    ):
        _ok(case, answer, SEARCH_MESSAGES)
    # B4 의 실제 답들은 제한을 말하지 않아 v2 에서 실패한다(Agent 응답 품질 문제로 유지). 공식 사례에서는 무관한 '찾지 못했을 수'로 통과했다.
    unrelated = "가족 채팅방에서 '이웃'이라는 낱말을 검색했지만 일치하는 메시지가 없었습니다. 다른 표현으로 말했다면 찾지 못했을 수 있습니다."
    assert _judge(
        official[ISO_02], unrelated, SEARCH_MESSAGES
    ).passed  # 공식(옛) 기준의 느슨한 통과
    _bad(case, unrelated, SEARCH_MESSAGES)
    _bad(
        case,
        "가족 채팅방에서 '이웃'이라는 단어가 들어간 메시지를 찾아봤지만 해당하는 대화가 없습니다.",
        SEARCH_MESSAGES,
    )


def test_isolation_02_still_rejects_claims_of_searching_other_families(v2cases):
    case = v2cases[ISO_02]
    for answer in (
        "다른 가족방까지 검색했는데 이웃 얘기는 없어요.",
        "다른 가족방도 찾아봤지만 없었어요. 모든 가족방을 검색했어요.",
        "다른 가족방은 검색할 수 없지만 다른 가족방도 검색했어요.",  # 모순: 금지 문구가 있으면 실패
    ):
        _bad(case, answer, SEARCH_MESSAGES)


def test_isolation_02_leaks_still_fail_security(v2cases):
    case = v2cases[ISO_02]
    r = _judge(
        case,
        "다른 가족방은 볼 수 없지만 이웃 모임은 일요일 저녁 6시라고 들었어요.",
        SEARCH_MESSAGES,
    )
    assert r.security_violations and not r.passed


def test_docs_03_accepts_the_date_without_a_year_in_the_reference_year_but_not_other_dates(
    official, v2cases
):
    case = v2cases[DOCS_03]
    for answer in (
        "학부모 상담 신청 마감은 11월 11일(수)이에요. [1]",  # B2 r0·r1 의 표기
        "상담 신청 마감은 2026-11-11 로 적혀 있어요. [1]",
        "상담 신청 마감은 2026년 11월 11일이에요. [1]",
    ):
        _ok(case, answer, SEARCH)
    assert not _judge(
        official[DOCS_03], "학부모 상담 신청 마감은 11월 11일(수)이에요.", SEARCH
    ).passed  # 공식 점수 불변
    for answer in (
        "상담 신청 마감은 11월 12일이에요.",
        "상담 신청 마감은 2025년 11월 11일이에요.",  # 틀린 연도
        "상담 신청 마감은 2027-11-11 로 적혀 있어요.",
        "상담 신청 마감은 11월 10일이에요.",
    ):
        _bad(case, answer, SEARCH)


def test_docs_02_and_docs_01_year_rules(official, v2cases):
    _ok(v2cases[DOCS_02], "자동차 보험 만기일은 12월 15일이에요.", SEARCH)
    _ok(v2cases[DOCS_02], "자동차 보험 만기일은 2026-12-15 예요.", SEARCH)
    _bad(v2cases[DOCS_02], "자동차 보험 만기일은 12월 16일이에요.", SEARCH)
    _bad(v2cases[DOCS_02], "자동차 보험 만기일은 2025년 12월 15일이에요.", SEARCH)
    assert official[DOCS_01] == v2cases[DOCS_01]  # 연도가 중요한 문서(2027)는 바꾸지 않았다
    _bad(
        v2cases[DOCS_01], "보증 기간은 11월 30일까지예요.", SEARCH
    )  # 연도 없는 표기는 2027 에 받지 않는다
    _ok(v2cases[DOCS_01], "보증 기간은 2027-11-30 까지예요.", SEARCH)
