"""메인 어시스턴트 프롬프트의 '이웃·다른 가족이 나오는 질문' 판단 지침(L0, 모델 호출 없음). E8 isolation-01.

dev 108 isolation-01: 옆집 모임 시간을 묻자 메인이 일정 담당·소통 담당·문서 검색을 모두 부르고 소통 Agent 는 검색어를 바꿔 반복 검색했다(호출 7~9회).
PR #539 의 첫 지침은 이를 줄였지만 국소 실모델 평가에서 도구를 전혀 부르지 않았고, 우리 가족이 가진 이웃 관련 기록(함께 잡은 일정·가족방 이야기·올린 문서)이
막힐 위험이 미검증이었다. 그래서 판단 기준을 '이웃이라는 사람·낱말'이 아니라 **정보가 어디에 있고 우리가 볼 수 있는지**로 고쳤다(2026-11-24 결정):
- 다른 가족이 자기 쪽에서만 가진 비공개 정보를 직접 요청 → 도구 없이 볼 수 없다고 안내
- 우리 가족이 가진 일정·대화·문서에 나오는 이웃 → 평소처럼 맞는 도구로 찾는다(차단하지 않는다)
- 출처가 불분명 → 묻는 내용에 맞는 한 곳만 한 번 확인하거나 되묻는다(일정·소통 담당을 늘 함께 부르지 않는다)
- 못 찾으면 반복·확장 검색을 멈추고 '우리 기록에서 확인되지 않은 부분'과 '다른 가족 정보라 볼 수 없는 부분'을 나눠 안내

중요: 이 지침은 **답하는 방식**을 정할 뿐 권한 통제가 아니다. 접근 검사(그룹 격리·`ensure_group_member`)는 서버가 하며 이 변경은 그 코드를 건드리지 않는다.
모델이 따르는지는 실제 모델 재평가로만 알 수 있다.
"""

from app.features.ai_assistant import agents
from app.features.ai_assistant.knowledge import rag_chat
from evals.agent_eval import case_files as cf
from evals.agent_eval import dev_cases

START = "이웃·옆집·다른 가족이 나오는 질문은 사람이나 낱말이 아니라 정보가 어디에 있고 우리가 볼 수 있는지로 판단하세요."
PRIVATE = "다른 가족이 자기 쪽에서만 가진 비공개 일정·대화·기록을 직접 알려 달라는 것이 분명하면 도구를 부르지 말고 볼 수 없는 정보라고 안내하세요."
OURS = "우리 가족이 가진 일정·대화·문서에 그 사람이 나오는 질문(함께 잡은 일정, 가족방에서 나온 이야기, 올려 둔 문서)은 평소처럼 맞는 도구로 찾으세요."
UNSURE = "정보가 어디에 있는지 분명하지 않으면 묻는 내용에 맞는 한 곳만 한 번 확인하세요"
CLARIFY = "도구 대신 어디에서 나온 이야기인지 되물어도 됩니다. 일정 담당과 소통 담당을 늘 함께 부르지 마세요."
STOP = "검색어를 바꿔 같은 곳을 다시 찾거나 다른 도구로 넓히지 말고"
SPLIT = "우리 가족 기록에서 확인되지 않은 부분과 다른 가족의 정보라 볼 수 없는 부분을 나눠 한 번에 알려 주세요."
CARE_START = (
    "가족의 건강에 관한 질문은 무엇을 찾는지(의도)와 정보가 어디에 있는지(출처)로 나눠 처리하세요."
)
OTHER_START = "자기 가족방과 다른 가족방"
DOC_RULE = "올려 둔 문서·영수증·고지서에 적힌 내용은 채팅이 아니니 search_knowledge 로 찾으세요."
MIXED = "자기 가족방과 다른 가족방(다른 가족)의 대화를 함께 찾아 달라는 요청(혼합 요청)은"
REFUSE = "다른 가족방·다른 가족의 정보만 알려 달라는 요청은 찾아볼 우리 가족방 대화가 없으니 도구를 부르지 말고 볼 수 없다고 직접 알려 주세요."
PARTS = (START, PRIVATE, OURS, UNSURE, CLARIFY, STOP, SPLIT)


def _note() -> str:
    return agents.PROMPT_NOTE


def _guidance() -> str:
    note = _note()
    start = note.index(START)
    end = note.index(SPLIT, start) + len(SPLIT)
    return note[start:end]


def test_the_note_judges_neighbor_questions_by_information_source_and_access():
    note = _note()
    for part in PARTS:
        assert part in note, part
    positions = [note.index(p) for p in PARTS]
    assert positions == sorted(positions)
    assert "사람이나 낱말이 아니라" in _guidance()


def test_a_neighbor_word_alone_does_not_block_search():
    guidance = _guidance()
    # 도구를 막는 문장은 '다른 가족이 자기 쪽에서만 가진 비공개 정보를 직접 요청'하는 한 곳뿐이다
    assert guidance.count("도구를 부르지 말고") == 1
    assert guidance.index("도구를 부르지 말고") > guidance.index("비공개 일정·대화·기록")
    assert OURS in guidance  # 우리 기록에 나오는 이웃은 평소처럼 찾는다


def test_the_guidance_does_not_make_both_agents_the_default():
    guidance = _guidance()
    assert "늘 함께 부르지 마세요" in guidance
    assert "각각 한 번" not in guidance
    assert "ask_schedule 과 ask_family_chat" not in guidance
    # 묻는 내용에 맞는 한 곳(일정·대화·문서)을 하나씩 짝지어 안내한다
    for pair in (
        "일정이면 ask_schedule",
        "대화 내용이면 ask_family_chat",
        "올려 둔 문서면 search_knowledge",
    ):
        assert pair in guidance, pair


def test_the_stop_sentence_separates_unconfirmed_from_inaccessible():
    guidance = _guidance()
    assert STOP in guidance and SPLIT in guidance
    assert guidance.index("확인되지 않은 부분") < guidance.index("볼 수 없는 부분")


def test_the_guidance_does_not_claim_to_enforce_permissions():
    guidance = _guidance()
    assert "권한" not in guidance  # 프롬프트는 답하는 방식일 뿐이다(접근 검사는 서버가 한다)
    assert "다른 가족의 정보를 찾아보세요" not in guidance


def test_the_guidance_sits_after_the_health_guidance_and_outside_the_other_family_span():
    note = _note()
    assert (
        note.index(OTHER_START) < note.index(DOC_RULE) < note.index(CARE_START) < note.index(START)
    )


def test_the_guidance_gives_no_evaluation_question_as_an_example():
    guidance = _guidance()
    cases = {c.id: c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}
    ids = [i for i in cases if i.startswith("s-dev-10-isolation-")]
    assert len(ids) == 3
    for cid in ids:
        question = cases[cid].question
        assert question not in guidance
        windows = {question[i : i + 10] for i in range(max(1, len(question) - 9))}
        assert not any(w in guidance for w in windows), cid
    assert "예:" not in guidance
    # 평가 정답 표현을 그대로 답하라고 시키지 않는다(공식 기대 문구 묶음의 낱말을 안내 문장으로 지정하지 않는다)
    assert "'" not in guidance


def test_the_main_system_prompt_sent_to_the_model_contains_the_guidance_once():
    prompt = rag_chat.system_prompt(with_agents=True)
    assert prompt.count(START) == 1
    assert START not in rag_chat.system_prompt(with_agents=False)


def test_the_existing_other_family_rules_and_the_mixed_request_rule_are_unchanged():
    note = _note()
    for kept in (
        REFUSE,
        MIXED,
        "사용자가 말한 검색 범위(다른 가족방까지 포함한다는 조건)와 찾으려는 주제를 지우거나",
        CARE_START,
        DOC_RULE,
    ):
        assert kept in note, kept
    assert note.index(MIXED) < note.index(START)
