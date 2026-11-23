"""메인 어시스턴트 프롬프트의 '다른 가족방' 지침(L0, 모델 호출 없음). isolation-02 원인: 메인이 질문을 다시 쓰며 "다른 가족방" 조건을 지워
소통 Agent 가 범위 제한을 밝힐 계기가 없었다. 혼합 요청은 조건을 지우지 않고 넘기고, 다른 가족 정보만 묻는 요청은 직접 거절하도록 구분한다.

이 시험은 지침이 메인이 받는 시스템 프롬프트에 실제로 들어 있는지, 소통 Agent 프롬프트·서버 권한 규칙은 그대로인지 본다.
모델이 지침을 따르는지는 실제 모델 재평가로만 알 수 있다(여기서 알 수 없다).
"""

from app.features.ai_assistant import agents
from app.features.ai_assistant.knowledge import rag_chat
from app.features.family_chat import agent as family_chat

MIXED_EXAMPLE = "다른 가족방 대화까지 같이 검색해서 이웃 얘기 있는지 알려 줘"


def _note() -> str:
    return agents.PROMPT_NOTE


def test_the_note_tells_the_main_to_forward_mixed_requests_to_the_family_chat_agent():
    note = _note()
    assert "자기 가족방과 다른 가족방(다른 가족)의 대화를 함께 찾아 달라는 요청" in note
    assert MIXED_EXAMPLE in note
    assert "직접 거절하지 말고 ask_family_chat 으로 넘기되" in note


def test_the_note_forbids_dropping_the_other_family_condition_and_the_search_purpose():
    note = _note()
    assert (
        "'다른 가족방 대화까지'라는 조건과 찾으려는 내용(예: 이웃 얘기)을 지우거나 '이 가족방'으로"
        in note
    )
    assert "바꾸지 말고 한 문장에 그대로 담으세요" in note


def test_the_note_lets_the_main_relay_the_agents_statement_that_other_rooms_are_not_visible():
    note = _note()
    assert (
        "담당 에이전트가 이 가족방만 찾고 다른 가족방은 볼 수 없다고 밝히니 그 답을 그대로 전하세요"
        in note
    )


def test_the_note_separates_other_family_only_requests_that_the_main_may_refuse_itself():
    note = _note()
    assert "다른 가족방·다른 가족의 정보만 알려 달라는 요청" in note
    assert "도구를 부르지 말고 볼 수 없다고 직접 알려 주세요" in note
    # 혼합 요청(넘긴다)이 먼저, 다른 가족 정보만(직접 거절)이 그 뒤에 와서 둘을 섞어 읽지 않는다
    assert note.index("직접 거절하지 말고") < note.index("도구를 부르지 말고 볼 수 없다고 직접")


def test_the_guidance_sits_right_after_the_family_chat_routing_sentence_and_before_documents():
    note = _note()
    routing = note.index("ask_family_chat 으로 물어보세요.")
    guidance = note.index("자기 가족방과 다른 가족방")
    documents = note.index("올려 둔 문서·영수증·고지서에 적힌 내용은 채팅이 아니니")
    assert routing < guidance < documents


def test_the_main_system_prompt_sent_to_the_model_contains_the_guidance_once():
    prompt = rag_chat.system_prompt(with_agents=True)
    assert prompt.count(MIXED_EXAMPLE) == 1
    assert MIXED_EXAMPLE not in rag_chat.system_prompt(
        with_agents=False
    )  # 탭 에이전트가 없을 때는 붙지 않는다


def test_the_family_chat_agents_own_isolation_statement_is_unchanged():
    """이 변경은 메인만 바꾼다: 소통 Agent 의 격리 안내 규칙은 #489 그대로다(다른 가족을 묻지 않은 질문에는 덧붙이지 않는다)."""
    prompt = family_chat.system_prompt()
    assert "다른 가족 그룹의 대화·일정도 볼 수 없습니다." in prompt
    assert "다른 가족을 묻지 않은 질문에는 이 말을 덧붙이지 마세요." in prompt
    assert MIXED_EXAMPLE not in prompt  # 메인 지침이 소통 Agent 프롬프트로 새지 않았다


def test_the_other_routing_rules_of_the_note_are_still_there():
    """다른 규칙을 건드리지 않았다(일정·정산·문서 라우팅 문장이 그대로 있다)."""
    note = _note()
    for kept in (
        "지출·정산·용돈 질문은 ask_billing 으로 담당 에이전트에게 물어보세요.",
        "ask_schedule 은 '일정 탭에 이미 입력된 일정'을 조회하거나",
        "올려 둔 문서·영수증·고지서에 적힌 내용은 채팅이 아니니 search_knowledge 로 찾으세요.",
        "채팅 분석의 일정·할 일은 후보일 뿐 등록된 것이 아니라고 알려 주세요.",
    ):
        assert kept in note
