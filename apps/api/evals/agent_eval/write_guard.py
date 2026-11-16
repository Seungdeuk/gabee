"""평가 중 일정 Agent 의 일정 쓰기가 실제 DB 를 바꾸기 전에 막는다(운영 코드는 고치지 않는다).

일정 Agent 가 DB 를 바꾸는 곳은 둘뿐이다(수정·삭제·공유 등록·부탁·습관 체크는 확인 카드만 만들고 `confirm` 은 부르지 않는다):
- `schedule.service.create`  (`agent/register.py::_created`, 제목·날짜가 있고 공유 대상이 없는 등록)
- `schedule.service.set_checked`  (`agent/checks.py::_mark`, 일정 체크·해제)

**범위는 일정 Agent 의 두 호출 지점뿐이다.** `schedule.service` 모듈 자체는 바꾸지 않는다: 일정 Agent 밖의 정상 쓰기(예: 메인의
`ai_assistant/reminders.py::resolve_reminder` 가 `schedule_service.create`·`set_checked` 를 부르는 "일정 잡기·했어요·오늘 다시")는 막지 않는다. 대신 두 호출 지점 모듈
(`register`·`checks`)의 `service` 이름을 세션(한 반복의 질문) 안에서만 프록시 객체로 바꾼다. 프록시는 `create`·`set_checked` 를 "실행하지 않고 도구 오류 형태의
`ApiError`" 를 올리는 함수로 돌려주고 나머지 속성은 원본 모듈에 위임한다. 끝나면(예외 포함) 원래 모듈로 되돌린다.
시도 자체의 관찰은 기록기(`eval_hook.observe_call`, `schedule.<intent>`)가 이미 남기므로 여기서는 다시 기록하지 않는다
(그 호출을 `is_error` 로 표시하면 채점기가 위반을 지우므로 표시하지도 않는다). 일정 Agent 의 예외는 메인 도구 루프가 도구 오류로 받아 모델에게 돌려준다.
감쌀 대상이 없거나 호출 지점이 `service` 모듈을 더 이상 쓰지 않으면 조용히 넘어가지 않고 `GuardUnavailable` 로 멈춘다.
한계: 일정 Agent 가 `service` 밖의 새 경로로 쓰면 판정(FAIL)은 되지만 차단은 안 된다.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from app.shared.errors import ApiError

GUARDED = ("create", "set_checked")  # schedule.service 의 DB 를 바꾸는 함수(일정 Agent 가 부른다)
CALL_SITES = (
    "register",
    "checks",
)  # `service.<함수>` 로 부르는 agent 모듈(이 모듈들의 `service` 가 같은 모듈이어야 막힌다)
BLOCKED_CODE = "eval_write_blocked"
BLOCKED_MESSAGE = "평가 중에는 일정 쓰기를 실행하지 않아요"


class GuardUnavailable(RuntimeError):
    """감쌀 대상이 운영 코드에서 바뀌어 차단을 보장할 수 없다."""


@dataclass
class Blocked:
    names: list[str] = field(default_factory=list)  # 막은 함수 이름(인자·본문은 남기지 않는다)


def _targets() -> tuple[Any, dict[str, Any]]:
    try:
        from app.features.schedule import service
        from app.features.schedule.agent import checks, register
    except ImportError as e:
        raise GuardUnavailable(f"일정 모듈을 불러올 수 없어 쓰기를 막을 수 없다: {e}") from e
    missing = [n for n in GUARDED if not callable(getattr(service, n, None))]
    if missing:
        raise GuardUnavailable(f"schedule.service 에 막을 함수가 없다: {missing}")
    sites = {"register": register, "checks": checks}
    moved = [n for n in CALL_SITES if getattr(sites[n], "service", None) is not service]
    if moved:
        raise GuardUnavailable(f"agent.{moved} 가 schedule.service 를 부르지 않아 막을 수 없다")
    return service, sites


class _GuardedService:
    """`schedule.service` 처럼 보이는 프록시: 쓰기 함수만 막고 나머지는 원본에 위임한다."""

    def __init__(self, real: Any, seen: Blocked) -> None:
        self._real = real
        self._seen = seen

    def __getattr__(self, name: str) -> Any:
        if name not in GUARDED:
            return getattr(self._real, name)

        def refuse(*args: Any, **kwargs: Any) -> Any:
            self._seen.names.append(name)
            raise ApiError(403, BLOCKED_CODE, BLOCKED_MESSAGE)

        refuse.__name__ = f"blocked_{name}"
        return refuse


@contextmanager
def blocked() -> Iterator[Blocked]:
    """이 안에서는 일정 Agent 의 두 호출 지점이 일정 쓰기를 실행하지 않고 `ApiError(eval_write_blocked)` 를 올린다. 나올 때 원래 모듈로 되돌린다."""
    service, sites = _targets()
    seen = Blocked()
    proxy = _GuardedService(service, seen)
    for n in CALL_SITES:
        sites[n].service = proxy
    try:
        yield seen
    finally:
        for n in CALL_SITES:
            sites[n].service = service


def count_events() -> int:
    """시험이 시도 전후의 일정 행 수를 비교하는 데 쓴다(임시 DB)."""
    from sqlalchemy import func, select

    from app.features.schedule.models import Event
    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(Event)) or 0)


__all__ = ["ApiError", "Blocked", "GuardUnavailable", "blocked", "count_events"]
