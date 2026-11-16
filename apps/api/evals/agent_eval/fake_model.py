"""대본형 가짜 모델: `transport.post_messages` 자리에 Anthropic 응답 모양의 가짜 응답을 돌려준다. 네트워크·키를 쓰지 않는다.

L2 실행기가 가짜 모델로 "가짜 모델 -> 실제 도구 -> 합성 DB -> 관찰 -> 채점 -> 저장" 전체를 돌려 보는 데 쓴다(실제 호출 0회). 이 가짜는 연결(배선)을
확인하려는 것이지 Agent 의 정확도를 재는 것이 아니다. 기본 대본의 최종 답은 사례의 기대 문구를 그대로 담으므로 통과는 "연결이 된다"는 뜻일 뿐이다.

- 어느 Agent 의 호출인지는 요청으로 가린다: 구조화 출력(`output_config`)은 일정, 시스템 프롬프트에 "가계(정산) 담당"이 있으면 정산, "가족 채팅 담당"이
  있으면 소통, 나머지는 메인이다(`app/shared/llm` 의 도구 루프가 Agent 마다 시스템 프롬프트를 따로 쓴다).
- 대본은 Agent 별 응답 목록이다. 응답 하나는 글(`say`), 도구 호출 한 번 이상(`call`·`round_of`), 또는 구조화 출력(`json_reply`)이다. 호출마다 다음 응답을
  꺼낸다. 마지막이 글이면 되풀이한다(메인이 직통 응답 없이 한 번 더 부를 때). 글이 아닌 응답이 바닥나면 `ScriptExhausted`(ValueError)로 모델 호출
  실패처럼 보이게 한다(앱이 LLM 실패로 처리한다). 인자는 값 또는 `ScriptContext` 를 받는 함수다(지출 id 처럼 시드가 정하는 값).
- 토큰 사용량은 결정적이다(응답마다 `FAKE_TOKENS`, 응답에 `tokens` 를 주면 그 값). 응답의 `model` 은 요청의 모델 이름을 그대로 돌려준다.
- 사례 대본: `default_script(legacy)` 는 기존 정산·메인 사례의 `tool`·`tool_any`·`main_tools`·`tool_args` 에 맞춘 도구 호출 뒤 `expect_contains`·`expect_any`
  를 담은 최종 답을 낸다. 쓰기 제안 사례처럼 인자를 질문에서 알아내야 하는 것은 `LEGACY_SCRIPT_OVERRIDES` 에 직접 쓴 대본이 있다.
  이 대본이 사례 기대를 못 채우면 대본의 한계이며, 기대값이나 채점은 바꾸지 않는다.
"""

import copy
import json
import re
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from app.shared.llm import transport

from .adapter import LegacyCase

FAKE_TOKENS = (1000, 200)  # (입력, 출력) 응답마다. 예산 시험이 값을 안다
DEFAULT_MODEL = "claude-haiku-5-5"
AGENTS = ("main", "billing", "family_chat", "schedule")


class ScriptExhausted(ValueError):  # noqa: N818  앱은 ValueError 를 모델 호출 실패로 처리한다
    """대본에 더 낼 응답이 없다."""


class ScriptError(RuntimeError):
    """대본이 값을 만들지 못했다(예: 시드에 없는 지출 제목을 찾으라고 했다)."""


class ScriptContext:
    """대본의 인자 함수가 시드가 만든 값(id)을 찾는 도구. 합성 DB 를 읽기만 한다."""

    def expense_id(self, title: str) -> str:
        from sqlalchemy import select

        from app.features.billing.models import Expense
        from app.shared.db import SessionLocal

        with SessionLocal() as db:
            found = db.scalars(
                select(Expense.id).where(Expense.title == title, Expense.deleted_at.is_(None))
            ).first()
        if found is None:
            raise ScriptError(f"제목이 '{title}' 인 지출이 시드에 없다")
        return found

    def allowance_request_id(self, child_name: str) -> str:
        from sqlalchemy import select

        from app.features.billing.models import AllowanceRequest
        from app.features.family_group.models import User
        from app.shared.db import SessionLocal

        with SessionLocal() as db:
            child = db.scalars(select(User.id).where(User.name == child_name)).first()
            found = (
                db.scalars(
                    select(AllowanceRequest.id).where(
                        AllowanceRequest.child_id == child, AllowanceRequest.status == "pending"
                    )
                ).first()
                if child
                else None
            )
        if found is None:
            raise ScriptError(f"'{child_name}' 의 대기 중인 용돈 요청이 시드에 없다")
        return found

    def event_id(self, title: str) -> str:
        """제목이 `title` 인 일정(삭제되지 않은 것)의 id. 일정 Agent 구조화 출력의 `event_ids` 에 시드가 정하는 id 를 넣을 때 쓴다."""
        from sqlalchemy import select

        from app.features.schedule.models import Event
        from app.shared.db import SessionLocal

        with SessionLocal() as db:
            found = db.scalars(
                select(Event.id).where(Event.title == title, Event.deleted_at.is_(None))
            ).first()
        if found is None:
            raise ScriptError(f"제목이 '{title}' 인 일정이 시드에 없다")
        return found

    def request_id(self, title: str) -> str:
        """제목이 `title` 인 부탁(일정 함께하기)의 id."""
        from sqlalchemy import select

        from app.features.schedule.models import EventRequest
        from app.shared.db import SessionLocal

        with SessionLocal() as db:
            found = db.scalars(select(EventRequest.id).where(EventRequest.title == title)).first()
        if found is None:
            raise ScriptError(f"제목이 '{title}' 인 부탁이 시드에 없다")
        return found


Args = Mapping[str, Any] | Callable[[ScriptContext], Mapping[str, Any]]


@dataclass(frozen=True)
class ToolUse:
    name: str
    args: Args = field(default_factory=dict)


@dataclass(frozen=True)
class Reply:
    """대본의 응답 하나: 글, 도구 호출들, 구조화 출력 중 하나."""

    text: str | None = None
    tools: tuple[ToolUse, ...] = ()
    data: Mapping[str, Any] | Callable[[ScriptContext], Mapping[str, Any]] | None = None
    tokens: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        kinds = [self.text is not None, bool(self.tools), self.data is not None]
        if sum(kinds) != 1:
            raise ValueError("응답은 글·도구 호출·구조화 출력 중 정확히 하나여야 한다")


Script = Mapping[str, Sequence[Reply]]


def say(text: str, tokens: tuple[int, int] | None = None) -> Reply:
    return Reply(text=text, tokens=tokens)


def call(name: str, args: Args | None = None, tokens: tuple[int, int] | None = None) -> Reply:
    return Reply(tools=(ToolUse(name, args or {}),), tokens=tokens)


def round_of(*uses: ToolUse, tokens: tuple[int, int] | None = None) -> Reply:
    """한 응답에서 도구를 여럿 부른다."""
    return Reply(tools=tuple(uses), tokens=tokens)


def json_reply(
    data: Mapping[str, Any] | Callable[[ScriptContext], Mapping[str, Any]],
    tokens: tuple[int, int] | None = None,
) -> Reply:
    return Reply(data=data, tokens=tokens)


def agent_of(body: Mapping[str, Any]) -> str:
    """요청을 낸 Agent. 구조화 출력은 일정, 시스템 프롬프트로 정산·소통을 가리고 나머지는 메인이다."""
    if "output_config" in body:
        return "schedule"
    system = str(body.get("system") or "")
    if "가계(정산) 담당" in system:
        return "billing"
    if "가족 채팅 담당" in system:
        return "family_chat"
    return "main"


class FakeModel:
    """`transport.post_messages(body, **kwargs)` 와 같은 모양으로 부를 수 있는 대본형 가짜.

    `record_bodies` 를 켜면(사전 점검이 켠다) 받은 요청 본문을 `bodies` 에 복사해 둔다(앱이 모델에게 보내려던 내용을 점검하려는 용도). 기본은 꺼짐.
    """

    record_bodies = False  # 클래스 수준 스위치: 사전 점검이 잠깐 켠다

    def __init__(
        self,
        script: Script,
        *,
        tokens: tuple[int, int] = FAKE_TOKENS,
        context: ScriptContext | None = None,
    ) -> None:
        unknown = set(script) - set(AGENTS)
        if unknown:
            raise ValueError(f"모르는 Agent 이름: {sorted(unknown)}")
        self._queues = {name: deque(replies) for name, replies in script.items()}
        self._last_text: dict[str, Reply] = {}
        self._tokens = tokens
        self._context = context or ScriptContext()
        self._next_id = 0
        self.calls = 0  # 호출 수(전송 함수가 실제로 불린 횟수)
        self.bodies: list[dict] = []  # `record_bodies` 가 켜졌을 때 받은 요청 본문의 복사본
        self.agents: list[str] = []  # 호출한 Agent 순서
        self.exhausted: list[str] = []  # 대본이 바닥난 Agent
        self.tool_results: dict[
            str, str
        ] = {}  # tool_use id -> 도구가 돌려준 글(실제 도구가 돈 증거)

    def _take(self, agent: str) -> Reply:
        queue = self._queues.get(agent)
        if queue:
            reply = queue.popleft()
            if reply.text is not None:
                self._last_text[agent] = reply
            return reply
        if agent in self._last_text:
            return self._last_text[agent]
        self.exhausted.append(agent)
        raise ScriptExhausted(f"{agent} 의 대본이 바닥났다")

    def _args(self, args: Args) -> dict[str, Any]:
        return dict(args(self._context) if callable(args) else args)

    def _scan_tool_results(self, body: Mapping[str, Any]) -> None:
        for message in body.get("messages") or []:
            content = message.get("content") if isinstance(message, Mapping) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, Mapping) and block.get("type") == "tool_result":
                    self.tool_results.setdefault(
                        str(block.get("tool_use_id")), str(block["content"])
                    )

    def __call__(self, body: dict, **_: Any) -> dict:
        self.calls += 1
        if FakeModel.record_bodies:
            self.bodies.append(copy.deepcopy(body))
        agent = agent_of(body)
        self.agents.append(agent)
        self._scan_tool_results(body)
        reply = self._take(agent)
        tokens_in, tokens_out = reply.tokens or self._tokens
        if reply.tools:
            content: list[dict[str, Any]] = []
            for use in reply.tools:
                self._next_id += 1
                content.append(
                    {
                        "type": "tool_use",
                        "id": f"toolu_fake_{self._next_id}",
                        "name": use.name,
                        "input": self._args(use.args),
                    }
                )
            stop = "tool_use"
        else:
            data = reply.data(self._context) if callable(reply.data) else reply.data
            text = reply.text if reply.text is not None else json.dumps(data, ensure_ascii=False)
            content = [{"type": "text", "text": text}]
            stop = "end_turn"
        return {
            "id": f"msg_fake_{self.calls}",
            "type": "message",
            "role": "assistant",
            "model": str(body.get("model") or DEFAULT_MODEL),
            "content": content,
            "stop_reason": stop,
            "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out},
        }


@contextmanager
def installed(fake: FakeModel) -> Iterator[FakeModel]:
    """`transport.post_messages` 를 가짜로 바꿔 끼운다(끝나면 되돌린다). 측정기(`usage.meter_llm_calls`)는 이 안쪽에서 연다."""
    real = transport.post_messages
    transport.post_messages = fake
    try:
        yield fake
    finally:
        transport.post_messages = real


# ---------- 기존 52건의 대본 ----------
_MONTH = re.compile(r"(?:(\d{4})\s*년\s*)?(\d{1,2})\s*월")


def _month_of(question: str, default: str = "2026-10") -> str:
    found = _MONTH.search(question)
    if not found:
        return default
    return f"{found.group(1) or '2026'}-{int(found.group(2)):02d}"


def _answer_text(legacy: LegacyCase) -> str:
    """기대 문구를 담은 최종 답. 금지 문구·끝말·정규식에 걸리는 후보는 건너뛴다."""
    case, ck = legacy.case, legacy.checks
    parts = [*case.expect.answer.contains, *ck.expect_any[:1]]
    if case.expect.outcome.proposals:
        parts.append("확인 버튼을 눌러야 반영돼요")
    candidates = [" ".join(dict.fromkeys(parts)), "알겠어요.", "네."]
    for text in candidates:
        if not text:
            continue
        clash = (
            any(t in text for t in case.expect.answer.not_contains)
            or any(text.strip().endswith(t) for t in ck.not_endswith)
            or any(re.search(r, text) for r in ck.not_regex)
        )
        if not clash:
            return text
    raise ScriptError(f"{case.id}: 기대 문구와 금지 조건이 맞물려 기본 답을 만들 수 없다")


def _billing_tools(legacy: LegacyCase) -> list[ToolUse]:
    ck = legacy.checks
    if ck.tool_mode == "exact":
        return [ToolUse(str(ck.tool), dict(ck.tool_args))]
    if ck.tool_mode == "any_of":
        return [ToolUse(ck.tool_any[0], dict(ck.tool_args))]
    if ck.tool_mode == "all_of":  # 모두 불러야 하므로 열거한 도구를 차례로 부른다
        return [ToolUse(name, dict(ck.tool_args)) for name in ck.tool_all]
    return []  # optional·none: 도구를 부르지 않는다


def _billing_steps(legacy: LegacyCase, text: str) -> list[Reply]:
    return [*(call(t.name, t.args) for t in _billing_tools(legacy)), say(text)]


def _main_billing_steps(legacy: LegacyCase, text: str) -> list[Reply]:
    question = legacy.case.question
    name = "list_expenses" if "내역" in question else "get_month_summary"
    return [call(name, {"month": _month_of(question)}), say(text)]


def default_script(legacy: LegacyCase) -> Script:
    """기존 사례의 도구 기대와 답 기대를 만족하는 기본 대본."""
    ck = legacy.checks
    text = _answer_text(legacy)
    if ck.agent == "billing":
        return {"billing": _billing_steps(legacy, text)}
    wanted = list(ck.main_tools or ())
    if not wanted:
        return {"main": [say(text)]}
    script: dict[str, list[Reply]] = {
        "main": [
            round_of(*(ToolUse(t, {"question": legacy.case.question}) for t in wanted)),
            say(text),
        ]
    }
    if "ask_billing" in wanted:
        script["billing"] = _main_billing_steps(legacy, text)
    if (
        "ask_schedule" in wanted
    ):  # 일정·가족채팅 하위 에이전트는 도구 없이 글로만 답하는 대본이면 연결 시험에 충분하다
        script["schedule"] = [say(text)]
    if "ask_family_chat" in wanted:
        script["family_chat"] = [say(text)]
    return script


def _propose(**args: Any) -> Reply:
    return call("propose_add_expense", args)


_CONFIRM = "확인 버튼을 눌러야 등록돼요"


def _expense(title: str) -> Callable[[ScriptContext], dict[str, Any]]:
    return lambda ctx: {"expense_id": ctx.expense_id(title)}


def _with_expense(title: str, **extra: Any) -> Callable[[ScriptContext], dict[str, Any]]:
    return lambda ctx: {"expense_id": ctx.expense_id(title), **extra}


def _decide(child: str, decision: str, **extra: Any) -> Callable[[ScriptContext], dict[str, Any]]:
    return lambda ctx: {
        "child_name": child,
        "request_id": ctx.allowance_request_id(child),
        "decision": decision,
        **extra,
    }


def _billing(*steps: Reply) -> Script:
    return {"billing": list(steps)}


# 인자를 질문에서 알아내거나 시드가 정하는 id 가 필요한 사례의 대본(쓰기 '제안' 도구는 DB 를 바꾸지 않는다)
LEGACY_SCRIPT_OVERRIDES: dict[str, Script] = {
    "b-write-propose": _billing(
        _propose(title="치과", amount=50000, date="2026-10-12"), say(_CONFIRM)
    ),
    "b-write-split": _billing(
        _propose(title="택시비", amount=12000, split_among=["지민", "수진"]), say(_CONFIRM)
    ),
    "b-write-split-unknown": _billing(
        _propose(title="택시비", amount=12000, split_among=["철수"]),
        say("철수라는 가족 구성원을 찾지 못해 제안하지 않았어요."),
    ),
    "b-write-all": _billing(_propose(title="점심 외식비", amount=40000), say(_CONFIRM)),
    "b-write-multi": _billing(
        round_of(
            ToolUse("propose_add_expense", {"title": "점심", "amount": 9000, "date": "2026-10-12"}),
            ToolUse("propose_add_expense", {"title": "커피", "amount": 4500, "date": "2026-10-12"}),
        ),
        say(_CONFIRM),
    ),
    "b-write-over-limit": _billing(
        round_of(
            *(
                ToolUse("propose_add_expense", {"title": t, "amount": a, "date": "2026-10-12"})
                for t, a in (("점심", 9000), ("커피", 4500), ("간식", 3000), ("택시", 12000))
            )
        ),
        say("세 건만 제안할 수 있어서 나머지는 다시 요청해 주세요. 확인 버튼을 눌러야 등록돼요"),
    ),
    "b-child-write": _billing(_propose(title="학교 준비물", amount=8000), say(_CONFIRM)),
    "b-write-negative": _billing(say("금액이 0보다 커야 해서 등록을 제안하지 않았어요.")),
    "b-update-amount": _billing(
        call("propose_update_expense", _with_expense("치과 진료", amount=50000)), say(_CONFIRM)
    ),
    "b-update-others": _billing(say("다른 사람이 낸 지출은 고칠 수 없어요.")),
    "b-update-settled": _billing(
        call("propose_update_expense", _with_expense("여행 숙소", amount=90000)),
        say("정산을 마친 지출은 고칠 수 없어요."),
    ),
    "b-update-split": _billing(say("나눌 사람은 바꿀 수 없어요.")),
    "b-delete-own": _billing(call("propose_delete_expense", _expense("치과 진료")), say(_CONFIRM)),
    "b-delete-others": _billing(
        call("propose_delete_expense", _expense("수진 간식")),
        say("다른 사람이 낸 지출은 지울 수 없어요."),
    ),
    "b-delete-settled": _billing(
        call("propose_delete_expense", _expense("여행 숙소")),
        say("정산을 마친 지출은 지울 수 없어요."),
    ),
    "b-paid-propose": _billing(
        call("propose_mark_paid", {"month": "2026-07", "from_name": "수진", "to_name": "지민"}),
        say(_CONFIRM),
    ),
    "b-paid-wrong-direction": _billing(
        call("propose_mark_paid", {"month": "2026-07", "from_name": "지민", "to_name": "수진"}),
        say("송금 목록에 없는 방향이에요."),
    ),
    "b-allowance-approve": _billing(
        call("propose_decide_allowance_request", _decide("민수", "approve")), say(_CONFIRM)
    ),
    "b-allowance-approve-amount": _billing(
        call("propose_decide_allowance_request", _decide("민수", "approve", amount=3000)),
        say(_CONFIRM),
    ),
    "b-allowance-reject": _billing(
        call("propose_decide_allowance_request", _decide("민수", "reject")), say(_CONFIRM)
    ),
    "b-allowance-not-manager": _billing(
        call("propose_decide_allowance_request", _decide("민수", "approve")),
        say("용돈 요청은 부모님이나 그룹을 만든 사람만 처리할 수 있어요."),
    ),
    "m-write-billing": {
        "main": [
            call("ask_billing", {"question": "치과 50000원 지출 등록해줘"}),
            say("확인 버튼을 눌러야 등록돼요"),
        ],
        "billing": [_propose(title="치과", amount=50000), say(_CONFIRM)],
    },
}


def script_for(legacy: LegacyCase) -> Script:
    """기존 사례의 대본: 직접 쓴 것이 있으면 그것, 아니면 기본 대본."""
    return LEGACY_SCRIPT_OVERRIDES.get(legacy.case.id) or default_script(legacy)
