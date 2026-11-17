"""관리자 챗봇의 도구 반복 루프(랭그래프).

모델이 도구를 부르면 도구를 실행해 결과를 돌려주고, 도구가 더 필요 없으면 답으로 끝난다. 예전에는 `run_agent` 의 `for` 문이었고,
같은 흐름을 그래프로 그렸다. 메인 채팅의 `ai_assistant/knowledge/rag_graph.py` 와 같은 방식이다(기능끼리 코드를 직접 부르지 않아 따로 둔다).

    START ─▶ model ──도구 호출 없음──────────────────────▶ END
              ▲  └─도구 호출 있음─▶ tools ──정한 횟수를 다 썼음─▶ END
              └──────────────────────┘ 그 밖에는 다시 model

모델은 랭체인 모델(`PostChatModel`), 도구는 랭체인 도구(`live.tools`)다. 요청마다 달라지는 값(모델, 도구, 횟수, 답)은 그래프 상태가
아니라 `Run` 에 담아 `config["configurable"]["run"]` 으로 넘긴다(그래프는 한 번만 만들어 모든 요청이 같이 쓴다).

랭스미스 기록은 `ADMIN_LANGSMITH_ENABLED` 가 켜져 있고 키가 있을 때만 이 그래프 실행에 붙는다(`_callbacks`). 서버 전체 추적
(`LANGSMITH_TRACING`)은 쓰지 않아서 메인 AI 채팅은 기록되지 않는다.

답변 단계 소식: 노드가 일을 시작할 때 `get_stream_writer()` 로 단계를 내보낸다. `stream_chat` 으로 돌리면 그 소식을 하나씩 받고,
`run_chat`(invoke)으로 돌리면 소식은 버려진다. 소식에는 단계와 도구의 화면용 이름(label)만 담고 질문·숫자·답은 넣지 않는다.

    {"step": "understand"}                  Claude 첫 호출(질문 이해)
    {"step": "tool", "label": "회원 수 확인"}  도구 하나 실행
    {"step": "write"}                       도구 결과를 받은 뒤 Claude 호출(답 작성)"""

from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.shared.config import settings
from app.shared.llm.chat_model import text_of

RUN_NAME = "admin_chatbot"  # 랭스미스 화면에 보이는 실행 이름


@dataclass
class Run:
    """요청 하나의 실행 문맥."""

    model: BaseChatModel
    tools: dict[str, BaseTool]
    max_steps: int
    steps: int = 0  # 모델을 부른 횟수
    answer: str = ""


class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def spec(tool: BaseTool) -> dict:
    """랭체인 도구를 Anthropic 도구 정의(이름·설명·input_schema)로 바꾼다. PostChatModel 이 이 모양을 그대로 보낸다."""
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": {"type": "object", "properties": dict(tool.args)},
    }


def _run(config: RunnableConfig) -> Run:
    return config["configurable"]["run"]


def _model(state: State, config: RunnableConfig) -> dict:
    run = _run(config)
    run.steps += 1
    # 첫 호출은 질문을 읽고 도구를 고르는 단계, 그 뒤는 도구 결과로 답을 쓰는 단계다
    get_stream_writer()({"step": "understand" if run.steps == 1 else "write"})
    reply = run.model.invoke(
        state["messages"], config
    )  # config 를 넘겨야 랭스미스에 모델 호출이 한 줄로 남는다
    if not reply.tool_calls:
        run.answer = text_of(reply)
    return {"messages": [reply]}


def _after_model(state: State) -> str:
    return "tools" if state["messages"][-1].tool_calls else END


def _tools(state: State, config: RunnableConfig) -> dict:
    run = _run(config)
    write = get_stream_writer()
    out: list[ToolMessage] = []
    for call in state["messages"][-1].tool_calls:
        tool = run.tools.get(call["name"])
        if tool is None:  # Claude 가 지어낸 이름. 화면에는 알리지 않는다
            out.append(
                ToolMessage(
                    content=f"없는 도구예요: {call['name']}",
                    tool_call_id=call["id"],
                    status="error",
                )
            )
        else:
            # 내부 도구 이름 대신 화면용 이름(label)만 보낸다
            write({"step": "tool", "label": (tool.metadata or {}).get("label") or tool.name})
            out.append(tool.invoke(call, config))  # 도구 호출을 그대로 주면 ToolMessage 로 돌려준다
    return {"messages": out}


def _after_tools(state: State, config: RunnableConfig) -> str:
    run = _run(config)
    return END if run.steps >= run.max_steps else "model"


def _build():
    graph = StateGraph(State)
    graph.add_node("model", _model)
    graph.add_node("tools", _tools)
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", _after_model, {"tools": "tools", END: END})
    graph.add_conditional_edges("tools", _after_tools, {"model": "model", END: END})
    return graph.compile()


GRAPH = _build()


@lru_cache(maxsize=1)
def _tracer(api_key: str, project: str) -> BaseCallbackHandler:
    """랭스미스 기록 장치. 키·프로젝트가 같으면 다시 만들지 않는다(보내기는 뒤에서 모아서 한다)."""
    from langchain_core.tracers.langchain import LangChainTracer
    from langsmith import Client

    return LangChainTracer(project_name=project, client=Client(api_key=api_key))


def _callbacks() -> list[BaseCallbackHandler]:
    """설정이 켜져 있고 키가 있을 때만 랭스미스 기록 장치를 준다. 아니면 빈 목록이라 밖으로 아무것도 나가지 않는다."""
    if not (settings.admin_langsmith_enabled and settings.admin_langsmith_api_key):
        return []
    return [_tracer(settings.admin_langsmith_api_key, settings.admin_langsmith_project)]


def _config(run: Run) -> RunnableConfig:
    return {
        "configurable": {"run": run},
        "recursion_limit": 50,
        "callbacks": _callbacks(),
        "run_name": RUN_NAME,
    }


def run_chat(run: Run, messages: list[BaseMessage]) -> Run:
    """그래프를 돌린다. 모델 호출의 예외는 그대로 올라간다(호출한 쪽이 503 으로 바꾼다).
    랭스미스로 보내는 일이 실패해도 답에는 영향이 없다(기록 장치는 오류를 로그로만 남긴다)."""
    GRAPH.invoke({"messages": messages}, config=_config(run))
    return run


def stream_chat(run: Run, messages: list[BaseMessage]) -> Iterator[dict]:
    """run_chat 과 같이 돌리되, 노드가 내보낸 단계 소식을 생기는 즉시 하나씩 돌려준다. 다 돌면 run.answer 에 답이 있다.
    예외는 run_chat 과 같이 그대로 올라간다."""
    yield from GRAPH.stream({"messages": messages}, config=_config(run), stream_mode="custom")
