"""메인 AI 채팅의 도구 반복 루프(랭그래프).

모델이 도구를 부르면 서버가 도구를 실행해 결과를 돌려주고, 도구가 더 필요 없으면 답으로 끝난다. 예전에는 `rag_chat.ask` 안의
`for` 문 4번이었고, 같은 흐름을 그래프로 그렸다. 모델로 가는 글은 먼저 가리고(mask), 모델이 쓴 답은 마지막에 되돌린다(restore).

    START ─▶ mask ─▶ model ──도구 호출 없음──────────────────────▶ restore ─▶ END
                      ▲  └─도구 호출 있음─▶ tools ──직통 응답 또는 4번째 호출이었음─▶ restore
                      └─────────────────────────┘ 그 밖에는 다시 model

이 파일은 흐름만 안다. 도구를 실제로 실행하고 출처·제안·확인 카드를 모으는 일은 `Run.handle`, 가리기·되돌리기는 `Run.mask`·`Run.restore`
(rag_chat 이 넘긴다, 구현은 rag_privacy)가 한다. 요청마다 달라지는 값(모델, 실행기, 단계 수, 답)은 그래프 상태가 아니라 `Run` 에 담아
`config["configurable"]["run"]` 으로 넘긴다(그래프는 한 번만 만들어 모든 요청이 같이 쓴다)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.shared.llm.chat_model import text_of


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
    ]  # 도구 호출 목록 -> 결과(도구 실행·출처 모으기는 호출한 쪽이 한다)
    max_steps: int
    mask: Callable[[str], str] | None = None  # 모델로 가는 글(질문·앞 대화)을 가린다. 없으면 그대로
    restore: Callable[[str], str] | None = None  # 모델이 쓴 최종 답을 되돌린다. 없으면 그대로
    steps: int = 0  # 모델을 부른 횟수
    answer: str = ""
    done: bool = False  # 직통 응답으로 끝났다


class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def _run(config: RunnableConfig) -> Run:
    return config["configurable"]["run"]


def _mask(state: State, config: RunnableConfig) -> dict:
    """질문·앞 대화의 글을 가린다. 같은 id 로 돌려줘 `add_messages` 가 원래 메시지를 이것으로 바꾼다."""
    run = _run(config)
    if run.mask is None:
        return {"messages": []}
    return {
        "messages": [
            message.model_copy(update={"content": run.mask(message.content)})
            for message in state["messages"]
        ]
    }


def _model(state: State, config: RunnableConfig) -> dict:
    run = _run(config)
    run.steps += 1
    reply = run.model.invoke(state["messages"])
    if not reply.tool_calls:
        run.answer = text_of(reply)
    return {"messages": [reply]}


def _after_model(state: State) -> str:
    return "tools" if state["messages"][-1].tool_calls else "restore"


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
    return "restore" if run.done or run.steps >= run.max_steps else "model"


def _restore(state: State, config: RunnableConfig) -> None:
    """모델이 쓴 답의 이름표를 되돌린다. 직통 응답(탭 에이전트의 글)은 이름표가 없는 실제 글이라 그대로 둔다."""
    run = _run(config)
    if run.restore is not None and run.answer and not run.done:
        run.answer = run.restore(run.answer)


def _build():
    graph = StateGraph(State)
    graph.add_node("mask", _mask)
    graph.add_node("model", _model)
    graph.add_node("tools", _tools)
    graph.add_node("restore", _restore)
    graph.add_edge(START, "mask")
    graph.add_edge("mask", "model")
    graph.add_conditional_edges("model", _after_model, {"tools": "tools", "restore": "restore"})
    graph.add_conditional_edges("tools", _after_tools, {"model": "model", "restore": "restore"})
    graph.add_edge("restore", END)
    return graph.compile()


GRAPH = _build()


def run_chat(run: Run, messages: list[BaseMessage]) -> Run:
    """그래프를 돌린다. 모델·도구 호출의 예외는 그대로 올라간다(호출한 쪽이 대체 답으로 바꾼다)."""
    GRAPH.invoke(
        {"messages": messages}, config={"configurable": {"run": run}, "recursion_limit": 50}
    )
    return run
