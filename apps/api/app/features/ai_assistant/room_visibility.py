"""가족 채팅방에서 `@가비` 로 부른 답을 방에 올려도 되는지 서버가 정한다.

메인 에이전트는 모든 도구를 쓸 수 있지만, 개인에게만 보여야 하는 정보(용돈 장부, 내가 결제할 구독, 위치, 내 일정, 민감 기록, 확인 버튼이
필요한 제안)가 한 번이라도 답에 쓰였으면 그 답은 방에 올리지 않고 질문한 사람에게만 보여 준다. 프롬프트로 부탁하지 않고 **어떤 도구가
불렸는지**로 판단하므로 모델이 어겨도 새지 않는다.

- 모르는 탭 에이전트·모르는 하위 도구는 **개인용**으로 본다(새 도구를 붙이고 여기에 올리지 않으면 방에 올라가지 않는다).
- 한 답에 공유 가능한 내용과 개인용 내용이 섞이면 쪼개지 않고 통째로 개인용이다.
- 이 판단은 방에서 부른 요청(`audience="room"`)에만 쓴다. 개인 대화는 항상 `private` 이다."""

from dataclasses import dataclass, field

ROOM = "room"
PRIVATE = "private"

# 기록 검색 도구: 가족 문서라 공유 가능하다(민감 기록이 쓰이면 개인용).
RECORD_TOOLS = frozenset({"search_knowledge", "get_item", "list_items"})

# 방에 올려도 되는 탭 에이전트와 그 하위 도구. 여기 없는 것은 개인용이다.
SHARED_AGENT_TOOLS: dict[str, frozenset[str]] = {
    "ask_billing": frozenset(
        {
            "get_month_summary",
            "list_expenses",
            "get_settlement",
            "get_settlement_manager",
            "list_subscriptions",
        }
    ),
    "ask_care": frozenset(
        {
            "get_daily",
            "get_today_summary",
            "list_records",
            "get_recommendations",
            "get_meal_suggestions",
            "list_meal_log",
            "get_meal_log_summary",
        }
    ),
    "ask_family_chat": frozenset({"search_messages", "analyze_recent_chat", "list_todos"}),
}

# 개인용이라고 이름을 아는 것: 사용자에게 안내하는 이유 글
PERSONAL_REASONS: dict[str, str] = {
    "list_allowances": "자녀 용돈 장부",
    "get_upcoming_payments": "내 결제 예정",
    "get_family_locations": "가족 위치",
    "propose_add_expense": "확인이 필요한 지출 등록 제안",
    "propose_record_meal": "확인이 필요한 식단 기록 제안",
    "propose_record_item": "확인이 필요한 안부 기록 제안",
    "ask_schedule": "내 일정",
}
SENSITIVE_REASON = "민감한 기록"
PROPOSAL_REASON = "확인 버튼이 필요한 제안"


@dataclass
class Visibility:
    visibility: str = ROOM
    reasons: list[str] = field(default_factory=list)

    def add(self, reason: str) -> None:
        self.visibility = PRIVATE
        if reason not in self.reasons:
            self.reasons.append(reason)


def judge(
    tool_calls: list[dict], used_sensitive: bool = False, has_proposals: bool = False
) -> Visibility:
    """메인 답의 도구 호출 기록(`AskResult.tool_calls`)으로 방에 올려도 되는지 정한다."""
    out = Visibility()
    if used_sensitive:
        out.add(SENSITIVE_REASON)
    if has_proposals:
        out.add(PROPOSAL_REASON)
    for call in tool_calls:
        name = call.get("name", "")
        if name in RECORD_TOOLS:
            continue
        shared = SHARED_AGENT_TOOLS.get(name)
        if shared is None:  # 모르는 도구·에이전트(일정 포함)는 개인용
            out.add(PERSONAL_REASONS.get(name, "개인 정보가 있을 수 있는 기능"))
            continue
        for sub in call.get("agent_tool_calls") or []:
            sub_name = sub.get("name", "")
            if sub_name not in shared:
                out.add(PERSONAL_REASONS.get(sub_name, "개인 정보가 있을 수 있는 기능"))
    return out
