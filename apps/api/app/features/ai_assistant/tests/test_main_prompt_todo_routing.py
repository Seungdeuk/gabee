"""메인 어시스턴트 프롬프트의 '할 일 조회 라우팅' 지침(L0, 모델 호출 없음). E8 compound-03.

dev 108 compound-03 r2: "오늘 해야 할 할 일"을 물었는데 메인이 일정 담당(`ask_schedule`)에만 물어 가족 공동 할 일(`ask_family_chat`)을 확인하지 않았다. 원인은
어느 목록인지 말하지 않은 할 일 질문의 담당이 프롬프트에 정해지지 않은 것이다. 확정 정책(2026-11-24):
- 가족 공동 할 일을 가리키거나 가족 채팅에서 정한 할 일 → `ask_family_chat` 만
- 내 일정 탭의 일정·할 일을 가리킴 → `ask_schedule` 만
- 어느 목록인지 불분명한 할 일 조회 → 둘 다
- '오늘' 같은 말은 날짜 조건일 뿐 이중 조회의 기준이 아님, 지출 등 다른 영역이 함께 오면 그 담당도 부름, 읽기 요청을 쓰기로 바꾸지 않음

이 시험은 지침이 메인 시스템 프롬프트에 실제로 들어 있는지, 기존 라우팅·담당 에이전트 설명·다른 에이전트 프롬프트는 그대로인지, 지침이 평가 질문을 예시로 들지 않는지 본다.
모델이 따르는지는 실제 모델 재평가로만 알 수 있다.
"""

from app.features.ai_assistant import agents
from app.features.ai_assistant.knowledge import rag_chat
from app.features.billing import agent as billing_agent
from app.features.family_chat import agent as family_chat_agent
from app.features.schedule.agent import ask as schedule_ask
from evals.agent_eval import case_files as cf
from evals.agent_eval import dev_cases

START = "할 일 조회는 어느 목록인지에 따라 나눠 부르세요."
SEPARATE = "가족이 함께 쓰는 목록을 가리키거나 가족 채팅에서 정한 할 일이면 ask_family_chat 만"
TAB_ONLY = "일정 탭의 일정·할 일을 가리키면 ask_schedule 만"
BOTH = "어느 목록인지 말하지 않은 할 일 질문은 ask_family_chat 과 ask_schedule 을 둘 다 불러"
DATE_ONLY = "기간 조건일 뿐 둘 다 부를지를 정하지 않습니다"
OTHER_AREAS = "지출 같은 다른 영역을 함께 물으면 그 담당도 부르세요"
READ_ONLY = "할 일을 묻는 조회 요청을 등록·수정 요청으로 바꾸지 마세요"


def _note() -> str:
    return agents.PROMPT_NOTE


def _guidance() -> str:
    note = _note()
    start = note.index(START)
    end = note.index("자기 가족방과 다른 가족방")
    return note[start:end]


def test_the_note_splits_todo_lookups_by_which_list_is_meant():
    note = _note()
    for part in (START, SEPARATE, TAB_ONLY, BOTH):
        assert part in note, part


def test_the_note_says_the_date_word_is_only_a_period_filter_and_other_areas_are_still_called():
    note = _note()
    assert DATE_ONLY in note and OTHER_AREAS in note


def test_the_note_keeps_read_requests_as_reads():
    assert READ_ONLY in _note()


def test_the_guidance_sits_right_after_the_family_chat_routing_sentence():
    note = _note()
    routing = note.index("ask_family_chat 으로 물어보세요.")
    guidance = note.index(START)
    mixed = note.index("자기 가족방과 다른 가족방")
    assert routing < guidance < mixed


def test_the_guidance_gives_no_evaluation_question_as_an_example():
    """평가 질문(dev compound-03·chat-03·isolation-03)과 같은 문장·10글자 창이 지침에 없다."""
    guidance = _guidance()
    cases = {c.id: c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}
    for cid in ("s-dev-07-compound-03", "s-dev-05-chat-03", "s-dev-10-isolation-03"):
        question = cases[cid].question
        assert question not in guidance
        windows = {question[i : i + 10] for i in range(max(1, len(question) - 9))}
        assert not any(w in guidance for w in windows), cid
    assert "(예:" not in guidance and "예:" not in guidance  # 따옴표 예시·'예:' 예시 없음


def test_the_main_system_prompt_sent_to_the_model_contains_the_guidance_once():
    prompt = rag_chat.system_prompt(with_agents=True)
    assert prompt.count(BOTH) == 1
    assert BOTH not in rag_chat.system_prompt(
        with_agents=False
    )  # 탭 에이전트가 없을 때는 붙지 않는다


def test_the_other_routing_rules_of_the_note_are_still_there():
    note = _note()
    for kept in (
        "지출·정산·용돈 질문은 ask_billing 으로 담당 에이전트에게 물어보세요.",
        "ask_schedule 은 '일정 탭에 이미 입력된 일정'을 조회하거나",
        "ask_family_chat 으로 물어보세요.",
        "올려 둔 문서·영수증·고지서에 적힌 내용은 채팅이 아니니 search_knowledge 로 찾으세요.",
        "어느 지출인지 제목·날짜·금액 중 아는 것을 ask_billing 을 부르기 전에 사용자에게 먼저 물어보세요",
        "자기 가족방과 다른 가족방(다른 가족)의 대화를 함께 찾아 달라는 요청(혼합 요청)은",
    ):
        assert kept in note, kept


def test_the_agent_descriptions_and_other_agent_prompts_are_unchanged():
    """이 변경은 메인 PROMPT_NOTE 만 바꾼다: 담당 에이전트 설명과 하위 Agent 프롬프트는 그대로다."""
    assert "가족 공동 할 일 목록을 조회해서 답한다" in family_chat_agent.DESCRIPTION
    assert "일정 탭에 이미 입력된 내 일정을 조회하고" in schedule_ask.DESCRIPTION
    assert "가계(정산) 탭 담당" in billing_agent.DESCRIPTION
    for text in (
        family_chat_agent.system_prompt(),
        billing_agent.system_prompt(),
    ):
        assert BOTH not in text and START not in text
