"""일정 Agent 응답으로 쓰기 요청의 결과를 가려 관찰 기록에 반영한다. 평가 쪽 판정이고 운영 코드는 바꾸지 않는다.

E3 훅은 구조화 출력의 의도(`schedule.register` 등)를 호출로 기록하지만, 그 뒤 코드가 실제로 무엇을 했는지(등록했는가, 되물었는가,
거절했는가)는 응답에만 있다. 정상적인 되묻기·거절은 실패가 아니므로 오류 표시를 하지 않고, 실제 실행 오류와 따로 다룬다. 채점기는
`is_error` 호출을 "아무것도 하지 못한 호출"로 보고 기대 호출에 대응시키지 않지만 금지·필수 도구 검사는 원본 호출 목록을 보기 때문에,
되묻기에 오류 표시를 달면 `tools.forbidden` 에 쓴 `schedule.register` 가 정상 되묻기에도 걸린다.

결과 상태와 관찰 기록에 반영하는 방식 (쓰기 의도 `WRITE_TOOLS["schedule"]` 에만 적용하고 query·recommend·not_schedule 은 `done`)
- `done`: 등록 완료·확인 카드가 생겼다. 응답에 카드·`pending_action` 이 있거나 알려진 거절 문구가 아닌 글이다(알 수 없는 글은 쓰기가 일어났다고 보수적으로 본다. 습관 체크처럼 카드 없이 글만 돌려주는 성공도 있다). 호출을 그대로 둔다.
- `clarified`: 필수 정보를 되물었다(응답에 `draft`). 한 일이 없으므로 호출을 기록에서 뺀다. 질문은 답에 남는다. 그래서 되물어야 하는 사례는
  `schedule.register` 를 금지하고 답을 확인하면 통과하고, 정보가 다 있는데 되물은 잘못된 되묻기는 기대한 호출이 없어 `missing_tool` 로 실패한다.
- `declined`: 거절·찾지 못함(`REFUSAL_TEXTS`: 남의 일정 삭제 거절, 대상을 못 찾음 등). 쓰기가 없으므로 호출을 뺀다(올바른 거절이 승인 없는 쓰기로 세어지지 않게).
- `gave_up`: 되묻는 횟수 한도를 넘겨 포기했다(`GIVE_UP_TEXTS`). 요청을 풀지 못한 것이라 호출을 `is_error` 로 표시한다.
- `error`: 실행 중 예외(모델 호출 실패 등). 호출을 `is_error` 로 표시한다. 예외가 분류 기록 전에 났으면 표시할 호출이 없어 그대로 둔다.
- 같은 요청을 다시 분류해(need_wider) 대체된 앞선 호출(`superseded`)은 한 일이 없으므로 항상 기록에서 뺀다(원본 호출 목록을 보는 금지·필수 도구 검사에 걸리지 않게).

한계: `REFUSAL_TEXTS` 는 코드의 문구 상수를 모은 목록이라 새 거절 문구가 생기면 `done` 으로 센다(시험은 상수가 사라지면 알려 준다). 메인의 `ask_schedule`
경로는 일정 Agent 의 `AgentResponse` 가 메인에게 보이지 않아 이 판정을 쓸 수 없다(E4c 에서 맞춘다).
"""

from collections.abc import Sequence
from typing import Any, Literal

from .write_tools import WRITE_TOOLS

Outcome = Literal["done", "clarified", "declined", "gave_up", "error"]
WRITE_INTENTS = frozenset(name.removeprefix("schedule.") for name in WRITE_TOOLS["schedule"])
# (모듈, 상수 이름): 쓰기 요청에 글만 돌려주는 알려진 거절·찾지 못함·되묻기 한도 초과 문구
_REFUSALS = (
    ("modify", "NOT_FOUND_TEXT"),
    ("modify", "NOT_OWNER_EDIT"),
    ("modify", "NOT_OWNER_DELETE"),
    ("modify", "SHARE_PERSONAL_ONLY"),
    ("modify", "NOT_SHARE_OWNER"),
    ("modify", "NOTHING_TEXT"),
    ("request_flow", "NOT_FOUND_TEXT"),
    ("request_flow", "NOT_SENDER_EDIT"),
    ("request_flow", "NOT_SENDER_CANCEL"),
    ("request_flow", "CONTENT_FIXED_TEXT"),
    ("request_flow", "WHO_HOW_TEXT"),
    ("request_flow", "NOTHING_TEXT"),
    ("request_flow", "NOT_UNDERSTOOD_TEXT"),
    ("request_flow", "NONE_FOUND_TEXT"),
    ("habits", "NOT_FOUND_TEXT"),
    ("habits", "NOT_MINE_TEXT"),
    ("checks", "NOT_FOUND_TEXT"),
)
_GIVE_UPS = (("register", "GIVE_UP_TEXT"), ("request_flow", "GIVE_UP_TEXT"))


def _texts(spec: tuple[tuple[str, str], ...]) -> frozenset[str]:
    from importlib import import_module

    return frozenset(
        getattr(import_module(f"app.features.schedule.agent.{module}"), name)
        for module, name in spec  # 상수가 사라지면 AttributeError 로 알린다
    )


def refusal_texts() -> frozenset[str]:
    return _texts(_REFUSALS)


def give_up_texts() -> frozenset[str]:
    return _texts(_GIVE_UPS)


def outcome_of(response: Any | None, error: BaseException | None = None) -> Outcome:
    """일정 Agent 응답(`AgentResponse`)과 실행 중 예외로 결과 상태를 가린다."""
    if error is not None:
        return "error"
    if response is None:
        raise ValueError("응답도 예외도 없다")
    if response.intent not in WRITE_INTENTS:
        return "done"
    if response.cards or response.pending_action is not None:
        return "done"
    if response.draft is not None:
        return "clarified"
    if response.text in give_up_texts():
        return "gave_up"
    return "declined" if response.text in refusal_texts() else "done"


def _is_schedule(call: dict) -> bool:
    return call.get("stage") == "schedule" and str(call.get("name", "")).startswith("schedule.")


def apply_outcome(calls: Sequence[dict], outcome: Outcome, intent: str | None = None) -> list[dict]:
    """결과를 반영한 새 관찰 호출 목록을 돌려준다(입력은 바꾸지 않는다).

    대체된(superseded) 일정 호출은 항상 뺀다. `intent` 는 응답의 의도이고 예외로 끝났을 때처럼 모르면 None 이다(가장 마지막 유효한 일정 호출을 쓴다).
    되묻기·거절·포기에서 그 호출이 기록에 없으면 훅이 꺼졌거나 단계가 빈 것이라 `ValueError` 로 알린다.
    """
    out = [dict(c) for c in calls if not (_is_schedule(c) and c.get("superseded"))]
    if outcome == "done":
        return out
    name = f"schedule.{intent}" if intent else None
    index = next(
        (
            i
            for i in range(len(out) - 1, -1, -1)
            if _is_schedule(out[i]) and (name is None or out[i].get("name") == name)
        ),
        None,
    )
    if index is None:
        if outcome == "error":
            return out  # 분류를 기록하기 전에 난 예외: 표시할 호출이 없다
        raise ValueError(f"{name or 'schedule.*'} 호출이 기록에 없다(훅이 꺼졌거나 단계가 비었다)")
    if outcome in ("clarified", "declined"):
        del out[index]
    else:  # gave_up, error
        out[index]["is_error"] = True
    return out
