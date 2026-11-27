"""메인 Agent 하이브리드 라우팅의 서버 1차 판정. 질문에 명시된 출처로 "허용 담당 집합"을 정하고, 모델은 그 안에서만 고른다.

요구사항: `docs/requirements/main-hybrid-routing.md`. 새 LLM 호출 없이 일반 표현 사전과 채널(audience)만 본다.
라우팅은 fail-open 이다: 판정이 애매하면(`unclear`) 아무것도 막지 않는다. 권한은 여기서 다루지 않는다(탭 Agent·서버 필터가 그대로 fail-closed).
평가 사례 문장이나 특정 낱말을 넣지 않는다. 사전은 "어느 기록을 보라는 말인가"를 나타내는 일반 표현만 둔다.
"""

import re
from dataclasses import dataclass

CHAT_HISTORY = "chat_history"
FAMILY_TODO = "family_todo"
SCHEDULE_TAB = "schedule_tab"
BILLING_LEDGER = "billing_ledger"
KNOWLEDGE_DOCS = "knowledge_docs"

# 출처 → 그 출처를 맡는 담당 도구. 문서는 담당 도구가 없다(문서 도구는 이 판정과 무관하게 늘 쓸 수 있다)
SOURCE_AGENTS: dict[str, frozenset[str]] = {
    CHAT_HISTORY: frozenset({"ask_family_chat"}),
    FAMILY_TODO: frozenset({"ask_family_chat"}),
    SCHEDULE_TAB: frozenset({"ask_schedule"}),
    BILLING_LEDGER: frozenset({"ask_billing"}),
    KNOWLEDGE_DOCS: frozenset(),
}

# 어느 기록을 보라는지 드러내는 표현. 내용 낱말(약속·모임·장보기 등)은 출처가 아니라서 넣지 않는다
_SOURCE_PATTERNS: dict[str, re.Pattern[str]] = {
    CHAT_HISTORY: re.compile(
        r"채팅|대화|가족\s*방|단톡|톡방|방에서|메시지|"
        r"(얘기|이야기)\s*(한|했|하던|나온|나왔|된)|(말|얘기)\s*(나온|나왔)"
    ),
    FAMILY_TODO: re.compile(r"(가족|공동|같이\s*(쓰는|하는))\s*(의\s*)?(할\s*일|투두)"),
    SCHEDULE_TAB: re.compile(r"일정|캘린더|달력|스케줄|부탁|약속\s*(을\s*)?(잡|넣|등록)"),
    BILLING_LEDGER: re.compile(r"지출|정산|용돈|장부|가계부|쓴\s*돈|돈\s*쓴|얼마\s*썼"),
    KNOWLEDGE_DOCS: re.compile(
        r"문서|서류|영수증|고지서|청구서|명세서|계약서|안내문|통신문|보증서|올린|올려\s*(둔|놓은)"
    ),
}

# 이런 말이 있으면 출처를 하나로 좁힐 수 없다고 보고 막지 않는다:
# - 목록을 말하지 않은 할 일(개인 채팅에서는 소통·일정 둘 다 보는 기존 규칙, #535)
# - 등록·추가처럼 어느 탭에 쓸지는 앞뒤 말에 달린 쓰기 표현
# - 앞선 대화를 가리키는 말(이전 턴은 판정에 쓰지 않는다)
_TODO = re.compile(r"할\s*일|투두")
_SCHEDULE_TODO = re.compile(r"(일정\s*탭|캘린더|내)\s*(의\s*|에\s*있는\s*)?(할\s*일|투두)")
_AMBIGUOUS = re.compile(
    r"등록|추가|넣어|잡아|잡혀|예약|"
    r"그거|그것|그걸|그건|아까|방금|위에|앞에서|첫\s*번째|두\s*번째|마지막|전부|모두"
)


@dataclass(frozen=True)
class Decision:
    """`sources` 가 비어 있으면 unclear(제한 없음). `allowed` 는 허용되는 `ask_*` 도구, unclear 면 None."""

    sources: frozenset[str]
    rule: str

    @property
    def unclear(self) -> bool:
        return not self.sources

    @property
    def compound(self) -> bool:
        return len(self.sources) > 1

    @property
    def allowed(self) -> frozenset[str] | None:
        if self.unclear:
            return None
        return frozenset().union(*(SOURCE_AGENTS[s] for s in self.sources))

    def permits(self, tool: str) -> bool:
        """이 담당 도구를 써도 되는가. `ask_*` 가 아닌 도구는 언제나 된다(호출한 쪽이 담당 도구만 묻는다)."""
        allowed = self.allowed
        return allowed is None or tool in allowed


UNCLEAR = Decision(frozenset(), "unclear")


def offered(specs: list[dict], decision: Decision, mode: str) -> list[dict]:
    """모델에 보여 줄 담당 도구. enforce 일 때만 허용 밖 담당을 뺀다(off·shadow 는 그대로)."""
    if mode != "enforce":
        return specs
    return [s for s in specs if decision.permits(s["name"])]


def decide(question: str, audience: str = "me") -> Decision:
    """질문 문장과 채널로 허용 담당 집합을 정한다. 질문 문장은 기록하지 않는다(호출한 쪽도 `rule` 만 남긴다)."""
    text = (question or "").strip()
    if not text:
        return UNCLEAR
    if _AMBIGUOUS.search(text):
        return Decision(frozenset(), "unclear:ambiguous")
    sources = {name for name, pattern in _SOURCE_PATTERNS.items() if pattern.search(text)}
    if _SCHEDULE_TODO.search(text):
        sources.add(SCHEDULE_TAB)
    elif _TODO.search(text) and FAMILY_TODO not in sources:
        # 어느 목록인지 말하지 않은 할 일. '일정'이 함께 있어도 할 일 쪽 목록은 정해지지 않는다
        if audience != "room":
            return Decision(frozenset(), "unclear:todo")
        sources.add(FAMILY_TODO)  # 가족방의 할 일은 가족 공동 목록이다(기존 프롬프트 규칙과 같다)
    if not sources:
        if audience == "room":
            # 가족방 @가비 질문이 어느 기록인지 말하지 않았고 일정·장부 표현도 없으면 그 방의 대화가 출처다(설계 메모 6절).
            # 쓰기·앞 대화 가리킴은 위에서 이미 unclear 로 빠졌다
            return Decision(frozenset({CHAT_HISTORY}), "room:default_chat")
        return UNCLEAR
    return Decision(frozenset(sources), "explicit:" + "+".join(sorted(sources)))


BLOCKED_TEXT = (
    "이 질문에는 이 담당을 쓰지 않습니다. 질문에 나온 기록의 담당이나 다른 도구로 답하세요."
)


def prompt_note(decision: Decision, mode: str) -> str:
    """enforce 에서 출처가 정해진 질문이면 시스템 프롬프트 끝에 붙일 한 줄(없으면 빈 글).

    시스템 프롬프트의 라우팅 문장에는 모든 담당 이름이 그대로 있어서, 도구 목록에서 뺀 담당도 모델이 부르려 한다(국소 평가 관찰)."""
    allowed = decision.allowed
    if mode != "enforce" or allowed is None:
        return ""
    if not allowed:
        return "\n\n이번 질문에는 담당 에이전트(ask_ 로 시작하는 도구)를 부르지 마세요."
    names = ", ".join(sorted(allowed))
    return (
        f"\n\n이번 질문에서 쓸 수 있는 담당 에이전트는 {names} 뿐입니다. "
        "위 안내에 다른 담당 이름이 나와도 이번에는 부르지 마세요."
    )
