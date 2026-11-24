"""메인 어시스턴트 프롬프트의 '대상이 정해지지 않은 지출 삭제·수정' 지침(L0, 모델 호출 없음). ambig-02 원인(E8).

dev 108 호출 기록: 사용자가 대상을 가리키지 않고 지출을 지워 달라고 하면 메인이 질문을 '가장 최근에 등록한 지출을 찾아서 알려 주고 삭제 확인을 요청해 달라'로
바꿔 정산 Agent 에 넘겼고(r1·r2), 정산 Agent 는 그대로 list_expenses 로 가장 최근 지출을 골라 제시했다. 정산 Agent 프롬프트에는 이미 '지울 지출이 분명하지
않으면 먼저 물어보세요'가 있어 원인은 메인이 대상을 임의로 정해 넘기는 데 있다. 확정 정책(2026-11-24): 대상이 특정되지 않으면 Agent 가 최근 지출을 고르지 않고
제목·날짜·금액 같은 식별 정보를 먼저 묻는다.

이 시험은 지침이 메인 시스템 프롬프트에 있는지, 명확한 요청의 기존 흐름·정산 Agent 규칙·서버 가드는 그대로인지, 지침이 평가 질문을 예시로 들지 않는지 본다.
모델이 따르는지는 실모델 재평가로만 알 수 있다.
"""

from app.features.ai_assistant import agents
from app.features.ai_assistant.knowledge import rag_chat
from app.features.billing import agent as billing_agent
from evals.agent_eval import case_files as cf
from evals.agent_eval import dev_cases

RULE = "어느 지출인지 제목·날짜·금액 중 아는 것을 ask_billing 을 부르기 전에 사용자에게 먼저 물어보세요"
NO_GUESS = "가장 최근 지출이나 다른 지출을 임의로 골라"
CLEAR_KEPT = "제목·금액·날짜 중 하나로 가리킨 요청은 지금처럼 그대로 ask_billing 으로 넘기세요"
AMBIG_02_QUESTION = "지난번에 낸 지출 지워 줘"


def _note() -> str:
    return agents.PROMPT_NOTE


def test_the_note_tells_the_main_to_ask_which_expense_before_calling_the_billing_agent():
    note = _note()
    assert "지출을 지우거나 고쳐 달라는 요청" in note
    assert RULE in note


def test_the_note_forbids_picking_the_latest_expense_or_asking_to_find_it_and_requesting_a_card():
    note = _note()
    assert NO_GUESS in note
    assert "찾아서 알려 달라고 넘기거나 삭제 확인 카드를 요청하지 마세요" in note


def test_a_request_that_names_the_expense_keeps_the_existing_flow():
    note = _note()
    assert CLEAR_KEPT in note
    # 지출 라우팅 문장은 그대로다
    assert "지출·정산·용돈 질문은 ask_billing 으로 담당 에이전트에게 물어보세요." in note
    assert "장부에 기록된 지출·정산 질문은 ask_billing 으로 확인하세요." in note


def test_the_guidance_sits_in_the_billing_routing_part_before_schedule_routing():
    note = _note()
    rule = note.index("지출을 지우거나 고쳐 달라는 요청")
    assert note.index("등록·기록 요청도 같은 담당 에이전트에게 넘기세요.") < rule
    assert rule < note.index("ask_schedule 은 '일정 탭에 이미 입력된 일정'을 조회하거나")


def test_the_guidance_gives_no_evaluation_question_as_an_example():
    """평가 질문과 같은 문장을 예시로 넣지 않는다(점수가 지침 이해가 아니라 문장 일치를 재면 안 된다)."""
    note = _note()
    start = note.index("지출을 지우거나 고쳐 달라는 요청")
    end = note.index("ask_schedule 은 '일정 탭에 이미 입력된 일정'을 조회하거나")
    guidance = note[start:end]
    assert AMBIG_02_QUESTION not in note
    # dev 사례의 질문과 10글자 창이 겹치지 않는다
    question = AMBIG_02_QUESTION
    windows = {question[i : i + 10] for i in range(max(1, len(question) - 9))}
    assert not any(w in guidance for w in windows)


def test_the_dev_case_and_its_expectations_are_unchanged():
    cases = {c.id: c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}
    case = cases["s-dev-08-ambig-02"]
    assert case.question == AMBIG_02_QUESTION
    assert case.expect.outcome.proposals == 0
    assert "propose_delete_expense" in case.expect.security.forbidden_writes


def test_the_main_system_prompt_sent_to_the_model_contains_the_guidance_once():
    prompt = rag_chat.system_prompt(with_agents=True)
    assert prompt.count(RULE) == 1
    assert RULE not in rag_chat.system_prompt(
        with_agents=False
    )  # 탭 에이전트가 없을 때는 붙지 않는다


def test_the_billing_agent_rules_and_the_server_guard_are_unchanged():
    """정산 Agent 의 기존 규칙(#453)은 그대로이고, 이 변경은 메인만 바꾼다."""
    billing = billing_agent.system_prompt()
    assert "'지난번에 낸 거', '그거'처럼 지울 지출이 분명하지 않으면 도구를 부르지 말고" in billing
    assert RULE not in billing
    from app.features.billing import target

    assert hasattr(target, "ensure_identified")
