"""할 일 라우팅 회귀 사례(`todo_routing_cases`)의 가짜 모델 대본(L2, 실제 호출 없음). 정상 대본은 정책대로 한 담당만 부르고, 위반 대본은 다른 담당까지 부른다."""

from . import fake_model as fm
from .dev_scripts import _ask, _query
from .fake_model import call, say
from .todo_routing_cases import FAMILY_ID, TAB_ID

FAMILY_QUESTION = "가족 공동 할 일 중 아직 안 끝난 것을 알려 줘"
TAB_QUESTION = "이번 주 일정 탭의 약속과 할 일을 알려 줘"
FAMILY_ANSWER = (
    "남은 공동 할 일은 우유 사기, 학교 준비물 챙기기, 보험 서류 제출, 도시락 재료 사기예요."
)
TAB_ANSWER = "이번 주 일정 탭에는 치과 진료, 학부모 상담, 가족 외식이 있어요."


def _family() -> list[fm.Reply]:
    return [call("list_todos", {"status": "open"}), say(FAMILY_ANSWER)]


def _tab() -> list[fm.Reply]:
    return [_query(TAB_ANSWER, events=("치과 진료", "학부모 상담", "가족 외식"))]


SCRIPTS: dict[str, dict] = {
    FAMILY_ID: {
        "main": [_ask("ask_family_chat", FAMILY_QUESTION), say(FAMILY_ANSWER)],
        "family_chat": _family(),
    },
    TAB_ID: {
        "main": [_ask("ask_schedule", TAB_QUESTION), say(TAB_ANSWER)],
        "schedule": _tab(),
    },
}

# 정책 위반(이중 조회): 명시한 목록 밖의 담당까지 부른다. 하네스가 금지 도구 위반(wrong_tool)으로 잡아야 한다.
VIOLATING: dict[str, dict] = {
    FAMILY_ID: {
        "main": [
            fm.round_of(
                fm.ToolUse("ask_family_chat", {"question": FAMILY_QUESTION}),
                fm.ToolUse("ask_schedule", {"question": FAMILY_QUESTION}),
            ),
            say(FAMILY_ANSWER),
        ],
        "family_chat": _family(),
        "schedule": _tab(),
    },
    TAB_ID: {
        "main": [
            fm.round_of(
                fm.ToolUse("ask_schedule", {"question": TAB_QUESTION}),
                fm.ToolUse("ask_family_chat", {"question": TAB_QUESTION}),
            ),
            say(TAB_ANSWER),
        ],
        "family_chat": _family(),
        "schedule": _tab(),
    },
}
