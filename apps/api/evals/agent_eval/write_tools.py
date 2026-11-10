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


def real_tool_names() -> dict[str, dict[str, frozenset[str]]]:
    """실제 코드가 만드는 도구 이름: {agent: {"all": ..., "read_only": ...}}. 도구는 만들기만 하고 부르지 않는다."""
    from app.features.ai_assistant import agents
    from app.features.ai_assistant.knowledge import tools
    from app.features.billing import agent as billing
    from app.features.family_chat import agent as family_chat
    from app.features.schedule.agent.schemas import INTENTS

    user = SimpleNamespace(id="u", name="평가")  # 도구를 만들 때는 DB·사용자를 읽지 않는다
    names = lambda items: frozenset(  # noqa: E731
        i["name"] if isinstance(i, dict) else i.name for i in items
    )
    billing_all = names(billing.build_tools(None, "g", user, proposed=[]))
    billing_read = names(billing.build_tools(None, "g", user, proposed=None))
    main_all = names(
        tools.TOOL_SPECS + agents.tool_specs() + tools.MEMORY_TOOL_SPECS + [tools.SHARE_TOOL_SPEC]
    )
    chat = names(family_chat.build_tools(None, "g", user, None))
    schedule = frozenset(f"schedule.{i}" for i in INTENTS if i != "not_schedule")
    return {
        "main": {"all": main_all, "read_only": main_all - WRITE_TOOLS["main"]},
        "billing": {"all": billing_all, "read_only": billing_read},
        "family_chat": {"all": chat, "read_only": chat},
        "schedule": {
            "all": schedule,
            "read_only": frozenset({"schedule.query", "schedule.recommend"}),
        },
    }


def verify_against_code() -> None:
    """목록이 실제 도구와 어긋나면 `ValueError` 로 무엇이 어긋났는지 알린다."""
    problems = []
    for agent, real in real_tool_names().items():
        listed = WRITE_TOOLS[agent] | READ_TOOLS[agent]
        if listed != real["all"]:
            problems.append(
                f"{agent}: 목록에만 {sorted(listed - real['all'])}, 코드에만 {sorted(real['all'] - listed)}"
            )
        elif WRITE_TOOLS[agent] != real["all"] - real["read_only"]:
            problems.append(f"{agent}: 쓰기 도구 분류가 코드와 다르다")
        if WRITE_TOOLS[agent] & READ_TOOLS[agent]:
            problems.append(f"{agent}: 읽기와 쓰기에 모두 있는 도구가 있다")
    if problems:
        raise ValueError("쓰기 도구 목록이 코드와 맞지 않는다: " + "; ".join(problems))
