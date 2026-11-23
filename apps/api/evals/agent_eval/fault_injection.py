"""평가 중 도구 오류를 주입한다(운영 코드는 고치지 않는다). `write_guard` 와 같은 방식의 호출 지점 프록시다.

배경: `tool_error` 사례(`s-dev-12-toolfail-01~03`)는 "도구가 실패했을 때 지어내지 않고 알리거나 재시도해 복구하는가"를 보려는 사례인데, 실행기가 오류를 만들지 않아(예전 머리 주석 'E4c 미구현')
실제 도구가 정상 값을 돌려줬다. 그러면 "확인할 수 없"을 요구하는 기준은 올바른 Agent 도 통과할 수 없고, 정상 값으로 답한 통과는 오류 복구를 검증한 것이 아니다.

주입 대상은 사례별 코드 상수(`SPECS`)다. 사례 파일(`cases_dev.json`, 정답지)은 바꾸지 않는다.
- 정산 도구(`get_month_summary`·`get_settlement`): 정산 Agent 모듈의 `service` 이름을 세션(한 반복의 질문) 안에서만 프록시로 바꾼다. 프록시는 대상 함수(`summary`·`settlement`)만
  `ApiError` 로 실패시키고 나머지 속성은 원본 모듈에 위임한다(`schedule`·`billing` 의 다른 쪽, 시드, API 는 영향 없음).
- 메인의 `ask_schedule`: `agents.call` 을 세션 안에서만 감싼다. `ask_schedule` 일 때만 실패시키고 다른 탭 에이전트 호출은 원본 그대로 부른다.
오류는 앱의 실제 오류 처리 경로(`ApiError` → 도구 결과 `{"error": ...}` · `is_error`)로 모델에 전달된다. 끝나면(예외 포함) 원래대로 되돌린다.
주입한 횟수와 도구 이름은 `Injected` 에 남아 관찰(`Observation.faults_injected`·`fault_tools`)과 결과 파일에 기록된다. 주입 명세가 있는 사례에서 한 번도 주입하지 못했다면
(모델이 그 도구를 부르지 않았거나 장치가 막힘) 실행기는 그 반복을 통과로 세지 않는다(`runner.fault_not_injected_detail`).
감쌀 대상이 없거나 운영 코드가 그 이름을 더 이상 쓰지 않으면 조용히 넘어가지 않고 `FaultUnavailable` 로 멈춘다.
한계: 호출 지점(`billing.agent.service`·`agents.call`)을 통하지 않는 새 경로는 주입되지 않는다(그 경우 주입 0건이 되어 통과로 세지 않는다).
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from app.shared.errors import ApiError

CODE = "eval_tool_failure"
MARKER = "[평가 주입 오류]"
MESSAGE = f"{MARKER} 일시적인 오류로 지금은 확인할 수 없어요"
BILLING = "billing"  # 정산 Agent 의 `service.<func>`
MAIN = "main"  # 메인 도구 루프의 `agents.call(<ask_*>)`


@dataclass(frozen=True)
class Fault:
    site: str  # BILLING | MAIN
    tool: str  # 모델에게 보이는 도구 이름(기록용)
    func: str  # 감쌀 함수 이름: BILLING 은 `service` 의 함수, MAIN 은 `ask_schedule` 같은 탭 에이전트 도구 이름
    times: int | None  # 앞에서 몇 번 실패시킬지. None 이면 끝까지 실패(복구할 수 없다)


# 사례 id -> 주입 명세. 여기 있는 사례는 주입이 한 번도 없으면 통과로 세지 않는다.
SPECS: dict[str, tuple[Fault, ...]] = {
    "s-dev-12-toolfail-01": (Fault(BILLING, "get_month_summary", "summary", None),),
    "s-dev-12-toolfail-02": (Fault(MAIN, "ask_schedule", "ask_schedule", None),),
    "s-dev-12-toolfail-03": (Fault(BILLING, "get_settlement", "settlement", 1),),
}
# 검증셋(val)의 주입 명세(개발셋 `SPECS` 와 따로 둔다). toolfail-01: 소통 담당 오류에서 대화 내용을 지어내지 않는가(`cases_val.json` 의 정답지는 건드리지 않는다).
# 여기 있는 사례도 주입이 한 번도 없으면 통과로 세지 않는다.
VAL_SPECS: dict[str, tuple[Fault, ...]] = {
    "s-val-12-toolfail-01": (Fault(MAIN, "ask_family_chat", "ask_family_chat", None),),
}


class FaultUnavailable(RuntimeError):
    """감쌀 대상이 운영 코드에서 바뀌어 오류를 주입할 수 없다."""


@dataclass
class Injected:
    names: list[str] = field(default_factory=list)  # 실패시킨 도구 이름(인자·본문은 남기지 않는다)

    @property
    def count(self) -> int:
        return len(self.names)


def specs_for(case_id: str) -> tuple[Fault, ...]:
    return SPECS.get(case_id) or VAL_SPECS.get(case_id, ())


class _Budget:
    """함수별로 앞에서 `times` 번만(None 이면 끝까지) 실패시킬지 센다."""

    def __init__(self, faults: tuple[Fault, ...], seen: Injected) -> None:
        self._faults = {f.func: f for f in faults}
        self._used: dict[str, int] = {}
        self._seen = seen

    def should_fail(self, func: str) -> bool:
        fault = self._faults.get(func)
        if fault is None:
            return False
        used = self._used.get(func, 0)
        if fault.times is not None and used >= fault.times:
            return False
        self._used[func] = used + 1
        self._seen.names.append(fault.tool)
        return True


def _raise() -> None:
    raise ApiError(503, CODE, MESSAGE)


class _FaultyService:
    """정산 `service` 모듈처럼 보이는 프록시: 명세의 함수만 실패시키고 나머지는 원본에 위임한다."""

    def __init__(self, real: Any, budget: _Budget, funcs: frozenset[str]) -> None:
        self._real = real
        self._budget = budget
        self._funcs = funcs

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._real, name)
        if name not in self._funcs:
            return target

        def maybe_fail(*args: Any, **kwargs: Any) -> Any:
            if self._budget.should_fail(name):
                _raise()
            return target(*args, **kwargs)

        maybe_fail.__name__ = f"faulty_{name}"
        return maybe_fail


def _billing_targets() -> tuple[Any, Any]:
    try:
        from app.features.billing import agent as billing_agent
        from app.features.billing import service
    except ImportError as e:
        raise FaultUnavailable(f"정산 모듈을 불러올 수 없어 오류를 주입할 수 없다: {e}") from e
    if getattr(billing_agent, "service", None) is not service:
        raise FaultUnavailable("정산 Agent 가 billing.service 를 부르지 않아 오류를 주입할 수 없다")
    return billing_agent, service


def _agents_module() -> Any:
    try:
        from app.features.ai_assistant import agents
    except ImportError as e:
        raise FaultUnavailable(
            f"탭 에이전트 모듈을 불러올 수 없어 오류를 주입할 수 없다: {e}"
        ) from e
    if not callable(getattr(agents, "call", None)):
        raise FaultUnavailable("agents.call 이 없어 오류를 주입할 수 없다")
    return agents


def _tool_name(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """`agents.call(db, group_id, user, name, args, post, audience)` 의 name."""
    if "name" in kwargs:
        return str(kwargs["name"])
    return str(args[3]) if len(args) > 3 else ""


@contextmanager
def injected(case_id: str) -> Iterator[Injected]:
    """이 안에서는 사례의 주입 명세대로 도구가 실패한다. 명세가 없는 사례는 아무것도 바꾸지 않는다. 나올 때(예외 포함) 원래대로 되돌린다."""
    seen = Injected()
    faults = specs_for(case_id)
    if not faults:
        yield seen
        return
    budget = _Budget(faults, seen)
    undo: list[Callable[[], None]] = []
    try:
        billing_funcs = frozenset(f.func for f in faults if f.site == BILLING)
        if billing_funcs:
            billing_agent, service = _billing_targets()
            billing_agent.service = _FaultyService(service, budget, billing_funcs)
            undo.append(lambda: setattr(billing_agent, "service", service))
        if any(f.site == MAIN for f in faults):
            agents = _agents_module()
            real_call = agents.call

            def faulty_call(*args: Any, **kwargs: Any) -> Any:
                if budget.should_fail(_tool_name(args, kwargs)):
                    _raise()
                return real_call(*args, **kwargs)

            agents.call = faulty_call
            undo.append(lambda: setattr(agents, "call", real_call))
        yield seen
    finally:
        for restore in reversed(undo):
            restore()


__all__ = [
    "CODE",
    "MARKER",
    "SPECS",
    "VAL_SPECS",
    "Fault",
    "FaultUnavailable",
    "Injected",
    "injected",
    "specs_for",
]
