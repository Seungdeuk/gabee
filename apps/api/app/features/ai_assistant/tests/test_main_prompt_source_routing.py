"""메인 어시스턴트 프롬프트의 '출처 판별' 지침(L0, 모델 호출 없음). Main Agent 이중 호출 개선.

출처가 분명한 질문에서 다른 담당까지 함께 부르던 문제(기준선 0/54 → 최종 평가 7/54, 국소 평가 1/9)를 줄이려고 두 곳을 최소로 바꿨다:
- "두 탭에 걸친 질문이면 둘 다 물어보세요." → "질문이 두 영역을 직접 묻는 복합 요청일 때만 필요한 담당을 각각 물어보세요."
- 가족 채팅 라우팅 문장과 할 일 조회 지침(#535 compound-03) 사이에 출처 판별 문장을 더했다: 출처가 하나로 정해지면 그 담당만, 채팅에서 뽑힌 후보는 일정 탭 조회와 섞지 않고,
  방 맥락이 붙어 있으면 목록을 말하지 않은 할 일 질문은 가족 공동 목록을 가리킨 것으로 본다. 불분명한 할 일 조회는 여전히 둘 다(compound-03 규칙 그대로).

이 시험은 지침이 시스템 프롬프트에 실제로 들어 있는지, #535 규칙과 기존 라우팅이 그대로인지, 지침이 평가 질문을 예시로 들지 않는지 본다. 모델이 따르는지는 실모델 평가로만 안다.
"""

from app.features.ai_assistant import agents
from app.features.ai_assistant.knowledge import rag_chat
from app.features.billing import agent as billing_agent
from app.features.family_chat import agent as family_chat_agent
from app.features.schedule.agent import ask as schedule_ask
from evals.agent_eval import case_files as cf
from evals.agent_eval import dev_cases

SOURCE_ONE = "질문이 가리키는 출처가 하나로 정해지면 그 출처의 담당만 부르고 다른 담당은 함께 부르거나 보충하려고 더 부르지 마세요."
TAB_ONLY = "일정 탭 자체를 묻는 질문은 ask_schedule 만"
CHAT_ONLY = "가족 공동 할 일을 묻는 질문은 ask_family_chat 만 부르세요"
CANDIDATES = "채팅에서 뽑힌 약속·할 일 후보는 일정 탭에 등록된 것이 아니니 일정 탭 조회와 섞지 말고"
USER_FIRST = "사용자가 말한 출처가 가장 우선입니다."
ROOM_DEFAULT = (
    "아래에 방 대화 내용이 함께 붙어 있다는 사실은 출처를 말하지 않았을 때만 보조 단서로 쓰세요"
)
ROOM_TAB = (
    "가족 채팅방에서도 사용자가 일정 탭의 일정(공동 일정 포함)을 말하면 ask_schedule 로 확인하세요."
)
ROOM_TODO = "가족 채팅방에서 한 할 일 질문은 일정 탭이 아니라 ask_family_chat 으로 물어봅니다."
KEEP_CHAT_SEARCH = "대화에서 이야기했거나 정한 내용(목록 포함)을 찾는 질문은 등록된 공동 할 일 조회로 바꾸지 말고 대화를 찾는 질문 그대로 넘기세요."
PRESERVE = "담당 에이전트에게 넘기는 질문에는 사용자가 찾는 대상·찾는 범위·기간·정보 출처를 바꾸거나 빼지 말고 그대로 담으세요."
# 2026-11-25 통합 평가 chat-02 r0 에서 대화 속 목록 질문을 공동 할 일로 좁힌 것으로 보인 옛 문장(다시 들어오면 안 된다)
OLD_ROOM_LIST = (
    "목록을 말하지 않은 할 일·목록 질문은 가족 공동 목록(ask_family_chat)을 가리킨 것으로 봅니다"
)
COMPOUND = "질문이 두 영역을 직접 묻는 복합 요청일 때만 필요한 담당을 각각 물어보세요."
OLD_BOTH = "두 탭에 걸친 질문이면 둘 다 물어보세요."
TODO_START = "할 일 조회는 어느 목록인지에 따라 나눠 부르세요."
TODO_BOTH = "어느 목록인지 말하지 않은 할 일 질문은 ask_family_chat 과 ask_schedule 을 둘 다 불러"
# addac7c9 국소 평가 chat-02 r0·r1: 가족방 보조 단서(소통만)와 '둘 다' 규칙이 부딪혀 첫 턴에 두 담당을 함께 불렀고, 넘김 질문에 말하지 않은 출처를 덧붙였다
NO_ADDED_SOURCE = "사용자가 말하지 않은 출처(다른 목록·다른 탭)를 덧붙이지도 마세요."
BOTH_SCOPE = (
    "이렇게 둘 다 부르는 것은 등록된 할 일을 조회할 때뿐이고, "
    "가족 채팅방에서 한 할 일 질문이나 대화에서 이야기한 목록·내용을 묻는 질문에는 쓰지 않습니다."
)
RELATED = (
    "s-dev-01-routing-02",
    "s-dev-02-schedq-01",
    "s-dev-02-schedq-02",
    "s-dev-02-schedq-03",
    "s-dev-04-care-02",
    "s-dev-05-chat-02",
    "s-dev-05-chat-03",
    "s-dev-07-compound-01",
    "s-dev-07-compound-02",
    "s-dev-07-compound-03",
    "s-dev-10-isolation-02",
)


def _note() -> str:
    return agents.PROMPT_NOTE


def _added() -> str:
    note = _note()
    return note[note.index(SOURCE_ONE) : note.index(TODO_START)]


def test_the_source_rule_is_in_the_note_and_the_old_double_lookup_sentence_is_narrowed():
    note = _note()
    for part in (SOURCE_ONE, TAB_ONLY, CHAT_ONLY, CANDIDATES, ROOM_DEFAULT, COMPOUND):
        assert part in note, part
    assert OLD_BOTH not in note


def test_the_room_cue_no_longer_turns_a_conversation_list_into_registered_todos():
    """방 단서는 '할 일 질문은 일정 탭이 아니라 소통 Agent' 까지만 정하고, 대화에서 정한 내용(목록 포함)을 찾는 질문은 대화 검색 그대로 넘긴다.
    일반 목록이라는 이유로 등록된 공동 할 일 목록으로 재해석하던 옛 문장은 없다. 질문 의미 보존 규칙이 함께 있다."""
    note = _note()
    assert OLD_ROOM_LIST not in note
    for part in (ROOM_TODO, KEEP_CHAT_SEARCH, PRESERVE):
        assert part in note, part
    assert note.index(ROOM_DEFAULT) < note.index(ROOM_TODO) < note.index(KEEP_CHAT_SEARCH)
    assert "장보기" not in _added()  # 특정 낱말로 하드코딩하지 않는다


def test_the_compound03_todo_rule_is_kept_as_the_exception_for_an_unclear_source():
    note = _note()
    assert TODO_START in note and TODO_BOTH in note
    assert note.index(SOURCE_ONE) < note.index(TODO_START)  # 일반 규칙 다음에 예외가 온다
    assert (
        "ask_family_chat 으로 물어보세요." in note[: note.index(SOURCE_ONE)]
    )  # 소통 라우팅 문장 바로 뒤


def test_the_both_rule_is_limited_to_registered_todos_and_yields_to_the_room_cue():
    """'둘 다'는 등록된 할 일 조회에만 쓰고, 가족방의 할 일 질문·대화 속 목록 질문에는 쓰지 않는다(바로 뒤에 범위 문장).
    단일 출처에서 보충 호출 금지·말하지 않은 출처 덧붙임 금지가 함께 있다. 특정 낱말·평가 질문 하드코딩 없음."""
    note = _note()
    for part in (BOTH_SCOPE, NO_ADDED_SOURCE, PRESERVE):
        assert part in note, part
    both = note.index(TODO_BOTH)
    assert both < note.index(BOTH_SCOPE) < both + 160  # 예외 문장 바로 뒤에서 범위를 좁힌다
    assert note.index(PRESERVE) < note.index(NO_ADDED_SOURCE) < note.index(TODO_START)
    assert note.index(ROOM_TODO) < note.index(
        BOTH_SCOPE
    )  # 방 단서가 먼저 나오고 '둘 다'가 그것을 덮지 않는다
    assert "보충하려고 더 부르지" in SOURCE_ONE
    tail = note[both : note.index("자기 가족방과 다른 가족방")]
    assert "장보기" not in tail and "장보기" not in note[note.index(PRESERVE) : both]
    cases = {c.id: c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}
    for cid in RELATED:
        question = cases[cid].question
        windows = {question[i : i + 10] for i in range(max(1, len(question) - 9))}
        for added in (BOTH_SCOPE, NO_ADDED_SOURCE):
            assert not any(w in added for w in windows), cid


def test_the_room_cue_exists_in_the_room_context_that_follows_the_note():
    assert "[방의 최근 대화]" in rag_chat.ROOM_CONTEXT_NOTE
    room = rag_chat.system_prompt(with_agents=True, room_context="지민: 안녕")
    # 방 맥락 블록은 노트보다 아래에 붙는다('아래에' 가 맞는다). 노트 문장은 블록 표지("방의 최근 대화")를 쓰지 않는다
    # (`test_room_context.py` 가 방이 아닐 때 그 표지가 시스템 프롬프트에 없음을 본다)
    assert "방의 최근 대화" not in agents.PROMPT_NOTE
    assert room.index(SOURCE_ONE) < room.index("[방의 최근 대화]")
    assert room.index(ROOM_DEFAULT) < room.index("[방의 최근 대화]")
    assert "방의 최근 대화" not in rag_chat.system_prompt(
        with_agents=True
    )  # 방이 아니면 블록이 없다


def test_the_policy_priority_is_user_stated_source_then_room_cue_only_when_unclear():
    """정책 우선순위: ① 사용자가 명시한 출처 ② 방 문맥은 출처가 불명확할 때 보조 ③ 방에서도 일정 탭을 명시하면 일정 Agent
    ④ 명시적 가족방 대화·공동 할 일은 소통 Agent 만 ⑤ 불분명한 일반 할 일·명확한 복합은 #535 유지 ⑥ 정산·문서 경로 유지."""
    note = _note()
    for part in (USER_FIRST, ROOM_DEFAULT, ROOM_TAB, CHAT_ONLY, TAB_ONLY, TODO_BOTH, COMPOUND):
        assert part in note, part
    i = {k: note.index(v) for k, v in dict(
        user=USER_FIRST, room=ROOM_DEFAULT, tab_in_room=ROOM_TAB, compound=TODO_BOTH
    ).items()}  # fmt: skip
    assert i["user"] < i["room"] < i["tab_in_room"] < i["compound"]  # 우선순위 순서로 적혀 있다
    assert (
        "출처를 말하지 않았을 때만" in note[i["room"] : i["room"] + 80]
    )  # 방 단서는 불명확할 때만
    assert "ask_billing" in note and "search_knowledge" in note  # ⑥ 정산·문서 경로 문장 유지


def test_the_rule_gives_no_evaluation_question_as_an_example():
    """관련 사례(routing-02·schedq·chat·compound·care-02·isolation-02)의 질문과 같은 문장·10글자 창이 추가 지침에 없다."""
    added = _added()
    cases = {c.id: c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}
    for cid in RELATED:
        question = cases[cid].question
        assert question not in added
        windows = {question[i : i + 10] for i in range(max(1, len(question) - 9))}
        assert not any(w in added for w in windows), (cid, [w for w in windows if w in added])
    assert "예:" not in added and "(예" not in added


def test_the_main_system_prompt_contains_the_rule_once_only_with_agents():
    prompt = rag_chat.system_prompt(with_agents=True)
    assert prompt.count(SOURCE_ONE) == 1 and prompt.count(TODO_BOTH) == 1
    assert SOURCE_ONE not in rag_chat.system_prompt(with_agents=False)


def test_the_other_routing_rules_are_still_there():
    note = _note()
    for kept in (
        "지출·정산·용돈 질문은 ask_billing 으로 담당 에이전트에게 물어보세요.",
        "ask_schedule 은 '일정 탭에 이미 입력된 일정'을 조회하거나",
        "올려 둔 문서·영수증·고지서에 적힌 내용은 채팅이 아니니 search_knowledge 로 찾으세요.",
        "ask_schedule 이 일정 탭에서 못 찾았다고 하면 답하기 전에 search_knowledge 로 올린 기록에서도 찾아보세요.",
        "어느 지출인지 제목·날짜·금액 중 아는 것을 ask_billing 을 부르기 전에 사용자에게 먼저 물어보세요",
        "자기 가족방과 다른 가족방(다른 가족)의 대화를 함께 찾아 달라는 요청(혼합 요청)은",
        "지출 같은 다른 영역을 함께 물으면 그 담당도 부르세요",
    ):
        assert kept in note, kept


def test_the_agent_descriptions_and_other_agent_prompts_are_unchanged():
    """메인 PROMPT_NOTE 만 바뀐다: 담당 에이전트 설명과 하위 Agent 프롬프트에는 이 지침이 없다."""
    assert "가족 공동 할 일 목록을 조회해서 답한다" in family_chat_agent.DESCRIPTION
    assert "일정 탭에 이미 입력된 내 일정을 조회하고" in schedule_ask.DESCRIPTION
    assert "가계(정산) 탭 담당" in billing_agent.DESCRIPTION
    for text in (family_chat_agent.system_prompt(), billing_agent.system_prompt()):
        assert SOURCE_ONE not in text and ROOM_DEFAULT not in text
