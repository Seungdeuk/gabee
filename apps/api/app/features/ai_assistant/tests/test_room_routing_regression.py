"""가족방 하이브리드 라우팅 회귀(결정론적). 가족방에서 출처를 말하지 않은 질문을 소통 Agent 로 제한하는 규칙(`room:default_chat`)이
필요한 담당을 잘못 막지 않는지 범주별로 본다. 문장은 평가 사례와 겹치지 않는 일반 표현이다.

`xfail(strict=True)` 는 2026-11-27 점검에서 찾은 **알려진 회귀**다(enforce 에서 필요한 담당이 빠진다). 규칙을 고치면 xpass 로
드러나 표시를 지우게 된다. 기본 모드는 off 라 운영에는 영향이 없다. 권한 규칙(1:1 일정 차단, 방 구성원 필터)은 라우팅과 별개다."""

import pytest

from app.features.ai_assistant import routing

ROOM = "room"
KNOWN = pytest.mark.xfail(
    strict=True,
    reason="알려진 회귀: 출처 표현 없는 가족방 질문을 소통 Agent 로만 제한(room:default_chat)",
)


def _allows(question: str, *tools: str) -> bool:
    decision = routing.decide(question, ROOM)
    return all(decision.permits(t) for t in tools)


# 1. 등록된 일정 조회
@pytest.mark.parametrize("q", ["이번 주 일정 알려줘", "캘린더에 뭐 있어?", "오늘 스케줄 알려줘"])
def test_schedule_lookup_with_a_schedule_word(q):
    assert _allows(q, "ask_schedule")


@pytest.mark.parametrize(
    "q",
    [
        pytest.param("내일 뭐 있어?", marks=KNOWN),
        pytest.param("토요일에 약속 있나?", marks=KNOWN),
        pytest.param("다음 주 화요일 비어 있어?", marks=KNOWN),
        pytest.param("엄마 병원 언제 가?", marks=KNOWN),
        pytest.param("이번 주말 계획 어떻게 돼?", marks=KNOWN),
    ],
)
def test_schedule_lookup_without_a_schedule_word(q):
    assert _allows(q, "ask_schedule")


# 2. 가족 정산 조회
@pytest.mark.parametrize(
    "q", ["이번 달 지출 얼마야?", "이번 달 정산 끝났어?", "용돈 줬어?", "이번 달 얼마 썼어?"]
)
def test_billing_lookup_with_a_ledger_word(q):
    assert _allows(q, "ask_billing")


@pytest.mark.parametrize(
    "q",
    [
        pytest.param("누가 돈 보내야 해?", marks=KNOWN),
        pytest.param("외식비 얼마 나왔어?", marks=KNOWN),
    ],
)
def test_billing_lookup_without_a_ledger_word(q):
    assert _allows(q, "ask_billing")


# 3. 일정 + 공동 할 일 복합
@pytest.mark.parametrize(
    "q", ["이번 주 일정이랑 우리가 할 일 알려줘", "내일 일정하고 할 일 정리해 줘"]
)
def test_schedule_and_family_todo(q):
    assert _allows(q, "ask_schedule", "ask_family_chat")


@pytest.mark.parametrize("q", [pytest.param("주말 계획이랑 해야 할 일 알려줘", marks=KNOWN)])
def test_schedule_without_a_schedule_word_and_family_todo(q):
    assert _allows(q, "ask_schedule", "ask_family_chat")


# 4. 명시적 다중 출처
@pytest.mark.parametrize(
    "q, tools",
    [
        ("채팅에서 나온 얘기랑 이번 달 지출 같이 봐 줘", ("ask_family_chat", "ask_billing")),
        ("대화에서 정한 약속 일정에 있는지 확인해 줘", ("ask_family_chat", "ask_schedule")),
        ("정산 현황이랑 일정 알려줘", ("ask_billing", "ask_schedule")),
    ],
)
def test_explicit_multiple_sources(q, tools):
    assert _allows(q, *tools)


# 5. 출처가 모호한 질문: 앞 대화를 가리키거나 쓰기 표현이면 제한하지 않는다
@pytest.mark.parametrize(
    "q", ["그거 어떻게 됐어?", "아까 말한 거 정리해 줘", "내일 병원 예약 넣어줘"]
)
def test_ambiguous_questions_are_not_limited(q):
    assert routing.decide(q, ROOM).unclear


# 6. 일반적인 가족 대화 검색: 소통 Agent 는 언제나 허용
@pytest.mark.parametrize(
    "q",
    [
        "치과 얘기 나온 거 찾아줘",
        "장보기 목록이 뭐였지?",
        "누가 차 가져온다고 했지?",
        "지난주에 무슨 얘기 했지?",
    ],
)
def test_family_chat_search_keeps_the_chat_agent(q):
    assert _allows(q, "ask_family_chat")


def test_personal_chat_is_not_affected_by_the_room_rule():
    """개인 채팅에서는 같은 문장이 unclear 라 막지 않는다."""
    for q in ("내일 뭐 있어?", "누가 돈 보내야 해?", "엄마 병원 언제 가?"):
        assert routing.decide(q, "me").unclear
