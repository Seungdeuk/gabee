"""도구를 부르며 답하는 반복 루프(랭그래프). 메인 AI 채팅과 탭 에이전트(`agent.run_agent`)가 함께 쓴다.

모델이 도구를 부르면 서버가 도구를 실행해 결과를 돌려주고, 도구가 더 필요 없으면 답으로 끝난다. 예전에는 두 곳(`rag_chat.ask`,
`agent.run_agent`)에 `for` 문으로 따로 있었고, 같은 흐름을 그래프 하나로 그렸다.

    START ─▶ model ──도구 호출 없음──────────────────────▶ END
              ▲  └─도구 호출 있음─▶ tools ──직통 응답 또는 max_steps 번째 호출이었음─▶ END
              └──────────────────────────┘ 그 밖에는 다시 model
    (max_steps 번째 호출이 도구 결과 뒤면 `tool_choice: none` 으로 도구를 못 쓰게 해 모은 근거로 답만 쓰게 한다)
    (서버 도구가 길어져 멈춘 응답 pause_turn 은 도구 칸 없이 바로 model 로 돌아간다)

이 파일은 흐름만 안다. 도구를 실제로 실행하고 결과를 글로 바꾸는 일(출처·제안·확인 카드 모으기, 길이 자르기, 오류 표시)은 `Run.handle` 을 넘긴
쪽이 한다. 모델 호출은 `PostChatModel` 이 `post` 로 하므로 호출 수 집계·재시도 정책(`transport.post_messages(retry=…)`)은 `post` 를 고른 쪽 그대로다.
요청마다 달라지는 값(모델, 실행기, 단계 수, 답)은 그래프 상태가 아니라 `Run` 에 담아 `config["configurable"]["run"]` 으로 넘긴다
(그래프는 한 번만 만들어 모든 요청이 같이 쓴다). 반드시 호출한 스레드에서 차례로 돈다(`ai_guard.tally_scope` 와 DB 세션이 그 스레드에 묶여 있다)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from . import eval_hook
from .chat_model import text_of
from .no_trace import no_trace


@dataclass
class ToolRound:
    """도구 한 차례의 결과. outputs 는 (도구 호출 id, 모델에게 줄 글, 오류 여부)이고,
    direct_answer 가 있으면 메인 모델을 다시 부르지 않고 그 글을 답으로 쓴다."""

    outputs: list[tuple[str, str, bool]]
    direct_answer: str | None = None


@dataclass
class Run:
    """요청 하나의 실행 문맥."""

    model: BaseChatModel
    handle: Callable[
        [list[dict]], ToolRound
    ]  # 도구 호출 목록 -> 결과(도구 실행·결과 글 만들기는 호출한 쪽이 한다)
    max_steps: int
    steps: int = 0  # 모델을 부른 횟수
    answer: str = ""
    finished: bool = False  # 모델이 도구 호출 없이 답을 냈다(글이 비어 있을 수는 있다)
    done: bool = False  # 직통 응답으로 끝났다
    stage: str = ""  # 평가 관찰용 단계 이름(main | billing | family_chat | schedule). 비어 있으면 기록하지 않는다
    force_first_tool: bool = (
        False  # 첫 모델 호출에서 도구 하나는 꼭 부르게 한다(`tool_choice: any`)
    )
    # 평가 관찰용: 단계 상한 때문에 도구 없이 최종 답을 받는 호출을 했다. 일반적인 도구 없는 답변은 아니다. 실행 흐름에는 쓰지 않는다.
    forced_final: bool = False
    messages: list[BaseMessage] = field(
        default_factory=list
    )  # 그래프가 끝난 뒤의 전체 대화(질문, 도구 호출·결과, 마지막 답). 호출한 쪽이 이어서 쓸 수 있다


TRUNCATED_NOTE = "\n\n(답이 길어서 여기서 끊겼어요. '계속'이라고 보내 주시면 이어서 알려 드릴게요.)"


class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def _run(config: RunnableConfig) -> Run:
    return config["configurable"]["run"]


def _model(state: State, config: RunnableConfig) -> dict:
    run = _run(config)
    run.steps += 1
    # 마지막 호출이 도구 결과 뒤라면 더 부르지 못하게 해 지금까지 찾은 근거로 답을 쓰게 한다(호출 수는 그대로)
    last_call = run.steps >= run.max_steps and isinstance(state["messages"][-1], ToolMessage)
    if last_call:
        run.forced_final = True
        reply = run.model.invoke(state["messages"], no_tools=True)
    elif run.force_first_tool and run.steps == 1:
        reply = run.model.invoke(state["messages"], force_tool=True)
    else:
        reply = run.model.invoke(state["messages"])
    eval_hook.observe_model(run.stage, reply)
    if not reply.tool_calls and not _keep_going(reply, run):
        run.answer, run.finished = text_of(reply), True
        if run.answer and reply.response_metadata.get("stop_reason") == "max_tokens":
            run.answer += (
                TRUNCATED_NOTE  # 길이 상한에서 끊긴 답은 끊겼다고 알린다(호출은 늘리지 않는다)
            )
    return {"messages": [reply]}


def _keep_going(reply: BaseMessage, run: Run) -> bool:
    """서버 도구(웹 검색)가 길어져 잠시 멈춘 응답이면 그대로 돌려보내 이어서 받는다. 아직 답이 끝난 게 아니다."""
    return reply.response_metadata.get("stop_reason") == "pause_turn" and run.steps < run.max_steps


def _after_model(state: State, config: RunnableConfig) -> str:
    reply = state["messages"][-1]
    if reply.tool_calls:
        return "tools"
    return "model" if _keep_going(reply, _run(config)) else END


def _tools(state: State, config: RunnableConfig) -> dict:
    run = _run(config)
    tool_calls = state["messages"][-1].tool_calls
    done = run.handle(tool_calls)
    eval_hook.observe_tools(run.stage, tool_calls, done.outputs)
    if done.direct_answer is not None:
        run.answer, run.done = done.direct_answer, True
    return {
        "messages": [
            ToolMessage(
                content=text, tool_call_id=call_id, status="error" if is_error else "success"
            )
            for call_id, text, is_error in done.outputs
        ]
    }


def _after_tools(state: State, config: RunnableConfig) -> str:
    run = _run(config)
    return END if run.done or run.steps >= run.max_steps else "model"


def _build():
    graph = StateGraph(State)
    graph.add_node("model", _model)
    graph.add_node("tools", _tools)
    graph.add_edge(START, "model")
    graph.add_conditional_edges(
        "model", _after_model, {"tools": "tools", "model": "model", END: END}
    )
    graph.add_conditional_edges("tools", _after_tools, {"model": "model", END: END})
    return graph.compile()


GRAPH = _build()


def run_graph(run: Run, messages: list[BaseMessage]) -> Run:
    """그래프를 돌린다. 모델·도구 호출의 예외는 그대로 올라간다(호출한 쪽이 대체 답이나 오류로 바꾼다)."""
    # 추적(LangSmith)은 환경변수와 상관없이 끈다: 켜지면 질문·도구 결과·답이 외부로 나간다
    with no_trace():
        final = GRAPH.invoke(
            {"messages": messages},
            # 한 번 반복이 노드 둘이라 단계 수의 두 배 남짓이면 충분하다(기본 50 은 25번 반복까지)
            config={
                "configurable": {"run": run},
                "recursion_limit": max(50, 2 * run.max_steps + 5),
            },
        )
    run.messages = list(final.get("messages") or [])
    # 평가가 켜져 있을 때만 계산한다(꺼져 있으면 아무것도 하지 않는다)
    if eval_hook.current() is not None:
        reached, forced = _step_limit_state(run, final)
        eval_hook.observe_step_limit(run.stage, reached, forced)
    return run


def _step_limit_state(run: Run, final: object) -> tuple[bool, bool]:
    """평가 관찰용 (단계 상한에 닿았는가, 상한 때문에 도구 없이 최종 답을 받았는가). 계산이 어긋나도 실행에는 영향이 없다.

    닿은 경우: 상한 때문에 도구 없는 마지막 호출을 했거나, 답 없이 상한에서 끊겼거나(마지막 단계의 도구 호출 뒤 끝), 서버 도구 대기(pause_turn)로
    끝났다. 마지막 단계에서 정상적으로 답한 경우는 닿은 것이 아니다.
    """
    try:
        messages = final.get("messages") if isinstance(final, dict) else None
        meta = getattr(messages[-1], "response_metadata", None) if messages else None
        paused = bool(meta) and meta.get("stop_reason") == "pause_turn"
        cut = not run.finished and not run.done and run.steps >= run.max_steps
        return run.forced_final or paused or cut, run.forced_final
    except Exception:  # noqa: BLE001  관찰이 운영 동작을 바꾸면 안 된다
        return False, run.forced_final
