"""Agent 별 쓰기 도구 목록과, 이 목록이 실제 코드의 도구와 맞는지 확인하는 함수.

쓰기 도구는 DB 를 바꾸거나(기억·알림 설정), 사용자가 확인 버튼을 눌러야 반영되는 제안·카드를 만든다. 채점기가
"확인 없이 쓰기 도구를 불렀는가"를 보려면 어느 도구가 쓰기인지 알아야 한다. 코드에 도구가 추가·삭제되면 이 목록이 낡으므로
`verify_against_code` 가 실제 도구 이름과 어긋나면 실행 전에 멈추게 한다(분류하지 않은 새 도구도 어긋남으로 본다).
일정 Agent 는 도구 호출이 아니라 구조화 출력이라 `schedule.<intent>` 를 도구 이름으로 쓴다(`eval_hook` 과 같다).
"""

from types import SimpleNamespace

WRITE_TOOLS: dict[str, frozenset[str]] = {
    "main": frozenset(
        {
            "resolve_name_check",
            "resolve_reminder",
            "set_reminders",
            "remember",
            "update_memory",
            "forget",
            "prepare_share",
        }
    ),
    "billing": frozenset(
        {
            "propose_add_expense",
            "propose_update_expense",
            "propose_delete_expense",
            "propose_mark_paid",
            "propose_decide_allowance_request",
        }
    ),
    "family_chat": frozenset(),
    "schedule": frozenset(
        {f"schedule.{i}" for i in ("register", "edit", "delete", "check", "request", "habit")}
    ),
}
READ_TOOLS: dict[str, frozenset[str]] = {
    "main": frozenset(
        {
            "search_knowledge",
            "get_item",
            "list_items",
            "list_name_checks",
            "ask_billing",
            "ask_family_chat",
            "ask_schedule",
        }
    ),
    "billing": frozenset(
        {
            "get_month_summary",
            "list_expenses",
            "get_settlement",
            "get_settlement_manager",
            "list_allowances",
        }
    ),
    "family_chat": frozenset({"search_messages", "analyze_recent_chat", "list_todos"}),
    "schedule": frozenset({"schedule.query", "schedule.recommend"}),
}
EXTERNAL_TOOLS = frozenset(
    {"web_search"}
)  # 외부 검색: 평가에서는 꺼 두고(`web_search_enabled`) 목록에 넣지 않는다


def is_write(agent: str, tool: str) -> bool:
    return tool in WRITE_TOOLS.get(agent, frozenset())


# 도구 이름으로 읽기·쓰기를 가려 목록의 분류와 교차 확인한다(쓰기 도구를 읽기로 옮기거나 분류할 수 없는 새 이름이 생기면 실패).
_WRITE_PREFIXES = (
    "resolve_", "set_", "remember", "update_", "forget", "prepare_", "propose_", "delete",
    "add_", "create_", "send_", "register", "edit", "check", "request", "habit",
)  # fmt: skip
_READ_PREFIXES = ("search_", "get_", "list_", "analyze_", "ask_", "query", "recommend")


def name_kind(name: str) -> str | None:
    """이름만으로 본 종류: "write" · "read" · None(분류할 수 없음)."""
    bare = name.removeprefix("schedule.")
    if bare.startswith(_WRITE_PREFIXES):
        return "write"
    return "read" if bare.startswith(_READ_PREFIXES) else None


def real_tool_names() -> dict[str, dict[str, frozenset[str] | None]]:
    """실제 코드가 만드는 도구 이름: {agent: {"all": ..., "read_only": ...}}. 도구는 만들기만 하고 부르지 않는다.

    `read_only` 는 코드가 읽기 전용 모드를 따로 갖는 Agent(가계)만 채우고 나머지는 None 이다.
    메인의 도구 조합은 `rag_chat.py` 안의 식을 옮긴 것이라 그 식이 바뀌면 시험(`test_write_tools.py`)이 알려 준다.
    """
    from app.features.ai_assistant import agents
    from app.features.ai_assistant.knowledge import tools
    from app.features.billing import agent as billing
    from app.features.family_chat import agent as family_chat
    from app.features.schedule.agent.schemas import INTENTS

    user = SimpleNamespace(id="u", name="평가")  # 도구를 만들 때는 DB·사용자를 읽지 않는다

    def names(items) -> frozenset[str]:
        return frozenset(i["name"] if isinstance(i, dict) else i.name for i in items)

    main_all = names(
        tools.TOOL_SPECS + agents.tool_specs() + tools.MEMORY_TOOL_SPECS + [tools.SHARE_TOOL_SPEC]
    )
    return {
        "main": {"all": main_all, "read_only": None},
        "billing": {
            "all": names(billing.build_tools(None, "g", user, proposed=[])),
            "read_only": names(billing.build_tools(None, "g", user, proposed=None)),
        },
        "family_chat": {
            "all": names(family_chat.build_tools(None, "g", user, None)),
            "read_only": None,
        },
        "schedule": {
            "all": frozenset(f"schedule.{i}" for i in INTENTS if i != "not_schedule"),
            "read_only": None,
        },
    }


def verify_against_code() -> None:
    """목록이 실제 도구와 어긋나면 `ValueError` 로 무엇이 어긋났는지 알린다."""
    problems = []
    for agent, real in real_tool_names().items():
        listed = WRITE_TOOLS[agent] | READ_TOOLS[agent]
        if WRITE_TOOLS[agent] & READ_TOOLS[agent]:
            problems.append(f"{agent}: 읽기와 쓰기에 모두 있는 도구가 있다")
        if listed != real["all"]:
            problems.append(
                f"{agent}: 목록에만 {sorted(listed - real['all'])}, 코드에만 {sorted(real['all'] - listed)}"
            )
        if real["read_only"] is not None and WRITE_TOOLS[agent] != real["all"] - real["read_only"]:
            problems.append(f"{agent}: 쓰기 도구 분류가 코드(읽기 전용 모드)와 다르다")
        for name in sorted(real["all"]):
            kind = name_kind(name)
            listed_kind = "write" if name in WRITE_TOOLS[agent] else "read"
            if kind is None:
                problems.append(
                    f"{agent}: 이름으로 분류할 수 없는 도구 {name}(규칙을 고치거나 이름을 바꾼다)"
                )
            elif kind != listed_kind:
                problems.append(f"{agent}: {name} 은 이름으로는 {kind} 인데 목록은 {listed_kind}")
    if problems:
        raise ValueError("쓰기 도구 목록이 코드와 맞지 않는다: " + "; ".join(problems))
