"""평가 전용 관찰 훅. Agent 평가(`apps/api/evals/agent_eval`)가 "어떤 도구를 어떤 인자로 불렀는가"를 보려고 쓴다.

평가가 `recording()` 으로 켜지 않으면 기록기가 없으므로 이 파일의 `observe_*` 는 아무것도 하지 않는다(운영 경로는 그대로다).
켜져도 기록은 메모리에만 두고 로그·파일·외부로 내보내지 않는다. 평가가 `Recording` 을 읽어 가서 `Observation` 으로 바꾼다
(이 파일은 평가 패키지를 가져오지 않는다: 공통 코드는 기능·평가 코드에 의존하지 않는다).
단계 이름(`stage`: main | billing | family_chat | schedule)은 호출한 쪽이 `tool_graph.Run.stage` 로 넘긴다. 비어 있으면 기록하지 않는다.
요청 하나는 한 스레드에서 차례로 돈다(`tool_graph` 머리말), 그래서 `contextvars` 로 충분하다.
"""

import copy
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Recording:
    calls: list[dict] = field(default_factory=list)  # stage, name, args, is_error, superseded
    steps: int = 0  # 도구 루프에서 모델을 부른 횟수
    llm_calls: int = 0  # 도구 루프의 모델 호출(일정 분류 호출은 세지 않는다)
    tokens_in: int = 0
    tokens_out: int = 0
    # 단계(stage)별로 도달·강제 최종 답 여부를 따로 둔다(중첩 Agent 가 서로 섞이지 않게). 같은 단계가 여러 번 돌면 하나라도 있으면 True
    stage_limits: dict[str, dict[str, bool]] = field(default_factory=dict)
    # 하이브리드 라우팅이 막았거나(enforce) 막았을(shadow) 담당 호출: mode, name, rule. 질문 문장은 담지 않는다.
    # `Observation` 형식을 바꾸지 않으려고 observation_fields 에는 넣지 않는다(측정 스크립트가 직접 읽는다)
    routing_blocks: list[dict] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)

    @property
    def step_limit_reached(self) -> bool:
        """어느 단계든 실행이 단계 상한에 닿았다."""
        return any(v["reached"] for v in self.stage_limits.values())

    @property
    def forced_final(self) -> bool:
        """어느 단계든 상한 때문에 도구 없이 최종 답을 받았다(상한 도달의 하위 사실)."""
        return any(v["forced_final"] for v in self.stage_limits.values())

    @property
    def step_limit_hit(self) -> bool:
        """옛 이름(하위 호환). `step_limit_reached` 와 같다."""
        return self.step_limit_reached

    def latency_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)

    def observation_fields(self) -> dict:
        """`Observation` 에 그대로 넘길 수 있는 값들(답·제안 등은 호출한 쪽이 채운다)."""
        return {
            "calls": copy.deepcopy(self.calls),
            "steps": self.steps,
            "llm_calls": self.llm_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "latency_ms": self.latency_ms(),
            "step_limit_reached": self.step_limit_reached,
            "forced_final": self.forced_final,
        }


_CURRENT: ContextVar[Recording | None] = ContextVar("agent_eval_recording", default=None)


@contextmanager
def recording() -> Iterator[Recording]:
    """이 안에서 일어난 도구 호출을 기록한다. 겹쳐 쓰면 안쪽이 따로 기록한다."""
    rec = Recording()
    token = _CURRENT.set(rec)
    try:
        yield rec
    finally:
        _CURRENT.reset(token)


def current() -> Recording | None:
    return _CURRENT.get()


def flatten_args(args: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """중첩 dict 를 `a.b` 키로 편다(채점기 매처는 dict 값을 맞출 수 없다)."""
    out: dict[str, Any] = {}
    for key, value in args.items():
        name = f"{prefix}{key}"
        if isinstance(value, Mapping):
            out.update(flatten_args(value, f"{name}."))
        else:
            out[name] = copy.deepcopy(value)
    return out


def observe_model(stage: str, reply: Any) -> None:
    """도구 루프가 모델을 한 번 부를 때마다."""
    rec = _CURRENT.get()
    if rec is None or not stage:
        return
    try:
        usage = getattr(reply, "usage_metadata", None)
        rec.steps += 1
        rec.llm_calls += 1
        if isinstance(usage, Mapping):
            rec.tokens_in += int(usage.get("input_tokens") or 0)
            rec.tokens_out += int(usage.get("output_tokens") or 0)
    except Exception:  # noqa: BLE001  관찰이 운영 동작을 바꾸면 안 된다
        return


def observe_tools(stage: str, tool_calls: list[dict], outputs: list[tuple[str, str, bool]]) -> None:
    """도구 한 차례. outputs 는 (도구 호출 id, 글, 오류 여부)."""
    rec = _CURRENT.get()
    if rec is None or not stage:
        return
    errors = {call_id: is_error for call_id, _text, is_error in outputs}
    for call in tool_calls:
        try:  # 한 호출이 이상해도 나머지는 기록한다
            entry = {
                "stage": stage,
                "name": call["name"],
                "args": flatten_args(call.get("args") or {}),
                "is_error": bool(errors.get(call.get("id"), False)),
                "superseded": False,
            }
        except Exception:  # noqa: BLE001  관찰이 운영 동작을 바꾸면 안 된다
            continue
        rec.calls.append(entry)


def observe_step_limit(stage: str, reached: bool, forced_final: bool = False) -> None:
    """도구 루프 하나가 끝날 때. `reached`: 단계 상한에 닿았다. `forced_final`: 그 때문에 도구 없이 최종 답을 받았다(닿은 경우에만)."""
    rec = _CURRENT.get()
    if rec is None or not stage:
        return
    entry = rec.stage_limits.setdefault(stage, {"reached": False, "forced_final": False})
    entry["reached"] = entry["reached"] or bool(reached or forced_final)
    entry["forced_final"] = entry["forced_final"] or bool(forced_final)


def observe_routing_block(stage: str, mode: str, name: str, rule: str) -> None:
    """하이브리드 라우팅이 담당 호출 하나를 막았거나(enforce) 막았을(shadow) 때."""
    rec = _CURRENT.get()
    if rec is None or not stage:
        return
    rec.routing_blocks.append({"stage": stage, "mode": mode, "name": name, "rule": rule})


def observe_call(stage: str, name: str, args: Mapping[str, Any]) -> None:
    """도구 호출이 아닌 구조화 출력(일정)을 같은 모양의 호출로 담는다. 일정 분류의 모델 호출 수·토큰은 캐시에 걸리면
    없을 수 있어 여기서 세지 않는다(실행기 E4 가 정한다)."""
    rec = _CURRENT.get()
    if rec is None or not stage:
        return
    try:
        rec.calls.append(
            {
                "stage": stage,
                "name": name,
                "args": flatten_args(args),
                "is_error": False,
                "superseded": False,
            }
        )
    except Exception:  # noqa: BLE001
        return


def mark_last(name: str, *, is_error: bool | None = None, superseded: bool | None = None) -> bool:
    """가장 마지막으로 기록된 `name` 호출에 표시를 단다(되묻기로 끝난 등록은 오류로, 같은 대상을 다시 제안하면 앞선 것을 대체로).
    그 뒤 코드의 결과로만 알 수 있는 표시라 호출한 쪽이 부른다. 기록이 없으면 False."""
    rec = _CURRENT.get()
    if rec is None:
        return False
    for call in reversed(rec.calls):
        if call["name"] == name:
            if is_error is not None:
                call["is_error"] = is_error
            if superseded is not None:
                call["superseded"] = superseded
            return True
    return False
