"""도구를 부르며 답하는 반복 루프(랭그래프). 메인 AI 채팅과 탭 에이전트(`agent.run_agent`)가 함께 쓴다.

모델이 도구를 부르면 서버가 도구를 실행해 결과를 돌려주고, 도구가 더 필요 없으면 답으로 끝난다. 예전에는 두 곳(`rag_chat.ask`,
`agent.run_agent`)에 `for` 문으로 따로 있었고, 같은 흐름을 그래프 하나로 그렸다.

    START ─▶ model ──도구 호출 없음──────────────────────▶ END
              ▲  └─도구 호출 있음─▶ tools ──직통 응답 또는 max_steps 번째 호출이었음─▶ END
              └──────────────────────────┘ 그 밖에는 다시 model
    (서버 도구가 길어져 멈춘 응답 pause_turn 은 도구 칸 없이 바로 model 로 돌아간다)

이 파일은 흐름만 안다. 도구를 실제로 실행하고 결과를 글로 바꾸는 일(출처·제안·확인 카드 모으기, 길이 자르기, 오류 표시)은 `Run.handle` 을 넘긴
쪽이 한다. 모델 호출은 `PostChatModel` 이 `post` 로 하므로 호출 수 집계·재시도 정책(`transport.post_messages(retry=…)`)은 `post` 를 고른 쪽 그대로다.
요청마다 달라지는 값(모델, 실행기, 단계 수, 답)은 그래프 상태가 아니라 `Run` 에 담아 `config["configurable"]["run"]` 으로 넘긴다
(그래프는 한 번만 만들어 모든 요청이 같이 쓴다). 반드시 호출한 스레드에서 차례로 돈다(`ai_guard.tally_scope` 와 DB 세션이 그 스레드에 묶여 있다)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

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


class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def _run(config: RunnableConfig) -> Run:
    return config["configurable"]["run"]


def _model(state: State, config: RunnableConfig) -> dict:
    run = _run(config)
    run.steps += 1
    reply = run.model.invoke(state["messages"])
    if not reply.tool_calls and not _keep_going(reply, run):
        run.answer, run.finished = text_of(reply), True
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
    done = run.handle(state["messages"][-1].tool_calls)
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
        GRAPH.invoke(
            {"messages": messages},
            # 한 번 반복이 노드 둘이라 단계 수의 두 배 남짓이면 충분하다(기본 50 은 25번 반복까지)
            config={
                "configurable": {"run": run},
                "recursion_limit": max(50, 2 * run.max_steps + 5),
            },
        )
    return run
