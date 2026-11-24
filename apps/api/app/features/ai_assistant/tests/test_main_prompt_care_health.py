"""메인 어시스턴트 프롬프트의 '건강 질문 처리' 지침(L0, 모델 호출 없음). E8 care-02 C1.

dev 108 care-02: "부모님 건강 상태가 이번 주에 어땠는지 요약해 줘"에 메인이 문서 검색·가족 채팅 검색·분석까지 호출 5~6회를 썼다. 앱에는 구조화된 건강 기록이 없고(돌봄 기록은
식단·위치뿐) 질문의 출처가 분명하지 않아서였다. 합의한 정책(2026-11-24): 특정 낱말이 아니라 **의도와 정보 출처**로 나눈다.
- 구조화된 건강 기록·수치 조회 → 지원하지 않는 기능이라 확인할 수 없다고 안내(도구 없음)
- 가족의 과거 발언·건강 관련 대화 검색 → `ask_family_chat`('채팅'이라는 낱말이 없어도)
- 업로드된 진료 서류·건강 관련 문서 검색 → `search_knowledge`
- 출처가 불분명한 건강 상태 질문 → 도구 없이 건강 기록이 없음을 안내하고 가족 대화 검색을 제안
- 가족 대화 내용과 의학적으로 확인된 사실을 구분하고 판단·진단하지 않는다

이 시험은 지침이 메인 시스템 프롬프트에 있는지, 기존 규칙(돌봄 항목·문서·다른 가족 지침)이 그대로인지, 지침이 평가 질문을 예시로 들지 않는지 본다.
모델이 따르는지는 실제 모델 재평가로만 알 수 있다.
"""

from app.features.ai_assistant import agents
from app.features.ai_assistant.knowledge import rag_chat
from evals.agent_eval import case_files as cf
from evals.agent_eval import dev_cases

START = (
    "가족의 건강에 관한 질문은 무엇을 찾는지(의도)와 정보가 어디에 있는지(출처)로 나눠 처리하세요."
)
RECORD = "지원하지 않는 기능이라 확인할 수 없다고 안내하세요"
CHAT = "'채팅'이라는 낱말이 없어도 ask_family_chat 으로 물어보세요"
DOCS = "올려 둔 진료 서류·검진 결과·처방전 같은 문서를 찾는 뜻이면 search_knowledge 로 찾으세요"
UNCLEAR = "도구를 부르지 말고 앱에 건강 기록이 없어 확인할 수 없다고 먼저 알린 뒤"
DISTINCT = "의학적으로 확인된 사실처럼 말하거나 건강 상태를 판단·진단하지 마세요"
DOC_RULE = "올려 둔 문서·영수증·고지서에 적힌 내용은 채팅이 아니니 search_knowledge 로 찾으세요."
OTHER_FAMILY_START = "자기 가족방과 다른 가족방"


def _note() -> str:
    return agents.PROMPT_NOTE


def _guidance() -> str:
    note = _note()
    start = note.index(START)
    end = note.index(DISTINCT, start) + len(DISTINCT)
    return note[start:end]


def test_the_note_splits_health_questions_by_intent_and_source():
    note = _note()
    for part in (START, RECORD, CHAT, DOCS, UNCLEAR, DISTINCT):
        assert part in note, part
    # 네 갈래가 이 순서로 온다: 기록·수치 → 대화 검색 → 문서 → 불분명 → 구분
    positions = [note.index(p) for p in (RECORD, CHAT, DOCS, UNCLEAR, DISTINCT)]
    assert positions == sorted(positions)


def test_the_rules_are_judged_by_intent_and_source_not_by_a_keyword():
    guidance = _guidance()
    assert "의도" in guidance and "출처" in guidance
    # 대화 검색은 '채팅'이라는 낱말이 없어도 성립해야 한다(낱말 포함 여부가 기준이 아니다)
    assert "낱말이 없어도" in guidance
    assert "키워드" not in guidance


def test_the_unclear_case_answers_without_tools_and_offers_a_family_chat_search():
    guidance = _guidance()
    unclear = guidance[guidance.index(UNCLEAR) :]
    assert "가족 대화에서 찾아볼 수 있다고 한 문장으로 제안하세요" in unclear


def test_family_talk_is_kept_apart_from_medically_confirmed_facts():
    guidance = _guidance()
    assert "'대화에서 그렇게 말했다'고만 전하고" in guidance
    assert DISTINCT in guidance


def test_the_guidance_sits_after_the_document_rule_and_outside_the_other_family_guidance():
    note = _note()
    other_start = note.index(OTHER_FAMILY_START)
    doc_rule = note.index(DOC_RULE)
    start = note.index(START)
    assert other_start < doc_rule < start  # 다른 가족 지침(자기 구간)과 섞이지 않는다


def test_the_guidance_gives_no_evaluation_question_as_an_example():
    """평가 질문(care-01~03·chat-01~03)과 같은 문장·10글자 창이 지침에 없다(점수가 지침 이해가 아니라 문장 일치를 재면 안 된다)."""
    guidance = _guidance()
    cases = {c.id: c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}
    ids = [i for i in cases if i.startswith(("s-dev-04-care-", "s-dev-05-chat-"))]
    assert len(ids) == 6
    for cid in ids:
        question = cases[cid].question
        assert question not in guidance
        windows = {question[i : i + 10] for i in range(max(1, len(question) - 9))}
        assert not any(w in guidance for w in windows), cid
    assert "(예:" not in guidance and "예:" not in guidance


def test_the_main_system_prompt_sent_to_the_model_contains_the_guidance_once():
    prompt = rag_chat.system_prompt(with_agents=True)
    assert prompt.count(START) == 1
    assert START not in rag_chat.system_prompt(
        with_agents=False
    )  # 탭 에이전트가 없을 때는 붙지 않는다


def test_the_existing_care_document_and_other_family_rules_are_unchanged():
    note = _note()
    for kept in (
        "돌봄 항목(데일리 체크 등)은 지금 확인할 수 없으니 모른다고 답하세요.",
        DOC_RULE,
        "다른 가족방·다른 가족의 정보만 알려 달라는 요청은 찾아볼 우리 가족방 대화가 없으니 도구를 부르지 말고 볼 수 없다고 직접 알려 주세요.",
        "자기 가족방과 다른 가족방(다른 가족)의 대화를 함께 찾아 달라는 요청(혼합 요청)은",
        "어느 지출인지 제목·날짜·금액 중 아는 것을 ask_billing 을 부르기 전에 사용자에게 먼저 물어보세요",
        "할 일 조회는 어느 목록인지에 따라 나눠 부르세요.",
    ):
        assert kept in note, kept
