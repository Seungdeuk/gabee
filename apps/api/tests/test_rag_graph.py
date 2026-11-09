"""도구 반복 루프(`shared/llm/tool_graph.py`, 랭그래프): 흐름·반복 상한·직통 응답·오류 전달. 메인 채팅과 탭 에이전트가 같이 쓴다."""

import json
import threading

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables.config import var_child_runnable_config

from app.shared.llm import agent, tool_graph
from app.shared.llm.agent import Tool
from app.shared.llm.chat_model import PostChatModel
from app.shared.llm.transport import LLMUnavailable


def _tool_use(call_id="t1", name="search_knowledge", args=None):
    return {"type": "tool_use", "id": call_id, "name": name, "input": args or {"query": "전기"}}


def _text(text):
    return {"content": [{"type": "text", "text": text}]}


def _calls(*blocks):
    return {"content": list(blocks)}


class Script:
    """모델이 차례로 돌려줄 응답과, 받은 요청·도구 호출을 기록한다."""

    def __init__(self, *replies, tool_outputs=None):
        self.replies = list(replies)
        self.bodies: list[dict] = []
        self.handled: list[list[dict]] = []
        self.tool_outputs = tool_outputs

    def post(self, body):
        self.bodies.append(body)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply

    def handle(self, calls):
        self.handled.append(calls)
        if self.tool_outputs is not None:
            return self.tool_outputs(calls)
        return tool_graph.ToolRound([(c["id"], '{"ok": true}', False) for c in calls])

    def run(self, max_steps=4, question="질문"):
        model = PostChatModel(post=self.post, llm_model="m", system="시스템")
        run = tool_graph.Run(model=model, handle=self.handle, max_steps=max_steps)
        return tool_graph.run_graph(run, [HumanMessage(content=question)])


# ---------- 흐름
def test_graph_has_the_expected_nodes_and_edges():
    graph = tool_graph.GRAPH.get_graph()
    assert set(graph.nodes) == {"__start__", "model", "tools", "__end__"}
    edges = {(e.source, e.target) for e in graph.edges}
    assert edges == {
        ("__start__", "model"),
        ("model", "tools"),
        ("model", "model"),  # 서버 도구가 길어져 멈춘 응답(pause_turn)을 이어 받는다
        ("model", "__end__"),
        ("tools", "model"),
        ("tools", "__end__"),
    }


def test_answer_without_tools_ends_after_one_model_call():
    script = Script(_text(" 안녕하세요 "))
    run = script.run()
    assert run.answer == "안녕하세요" and run.steps == 1 and not run.done
    assert script.handled == []


def test_tool_call_then_answer():
    script = Script(_calls(_tool_use()), _text("찾았어요 [1]"))
    run = script.run()
    assert run.answer == "찾았어요 [1]" and run.steps == 2
    assert script.handled == [
        [{"type": "tool_call", "id": "t1", "name": "search_knowledge", "args": {"query": "전기"}}]
    ]
    # 두 번째 요청에는 모델의 도구 호출(원본 블록)과 도구 결과가 순서대로 들어 있다
    second = script.bodies[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert second[1]["content"] == [_tool_use()]
    assert second[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "t1", "content": '{"ok": true}', "is_error": False}
    ]


def test_several_tool_calls_in_one_reply_share_one_user_message():
    script = Script(_calls(_tool_use("a"), _tool_use("b", "list_items", {})), _text("끝"))
    script.run()
    assert [c["id"] for c in script.handled[0]] == ["a", "b"]
    results = script.bodies[1]["messages"][2]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]


def test_tool_errors_are_marked_so_the_model_can_see_them():
    def outputs(calls):
        return tool_graph.ToolRound([(calls[0]["id"], '{"error": "없어요"}', True)])

    script = Script(_calls(_tool_use()), _text("못 찾았어요"), tool_outputs=outputs)
    script.run()
    (result,) = script.bodies[1]["messages"][2]["content"]
    assert result["is_error"] is True and "없어요" in result["content"]


# ---------- 직통 응답
def test_direct_answer_ends_the_loop_without_calling_the_model_again():
    def outputs(calls):
        return tool_graph.ToolRound([(calls[0]["id"], "{}", False)], direct_answer="에이전트의 답")

    script = Script(
        _calls(_tool_use(name="ask_billing", args={"question": "지출"})), tool_outputs=outputs
    )
    run = script.run()
    assert run.answer == "에이전트의 답" and run.done and run.steps == 1
    assert len(script.bodies) == 1  # 메인 모델 호출 1번 절약


# ---------- 반복 상한
def test_the_loop_stops_after_max_steps_without_an_answer():
    script = Script(_calls(_tool_use()))  # 모델이 계속 도구만 부른다
    run = script.run(max_steps=3)
    assert run.steps == 3 and len(script.handled) == 3  # 마지막 호출의 도구도 실행하고 끝난다
    assert run.answer == "" and not run.done  # 답이 없으면 호출한 쪽이 대체 답을 쓴다


def test_default_limit_of_the_main_chat_is_four_calls():
    from app.features.ai_assistant.knowledge import rag_chat

    assert rag_chat.MAX_STEPS == 4


# ---------- 오류
@pytest.mark.parametrize("error", [httpx.ConnectError("x"), ValueError("json"), KeyError("id")])
def test_errors_from_the_model_call_reach_the_caller_unchanged(error):
    with pytest.raises(type(error)):
        Script(error).run()


def test_errors_from_the_tool_handler_reach_the_caller_unchanged():
    def outputs(calls):
        raise ValueError("도구 실패")

    with pytest.raises(ValueError):
        Script(_calls(_tool_use()), tool_outputs=outputs).run()


def test_a_tool_use_without_an_id_raises_key_error():
    with pytest.raises(KeyError):
        Script(_calls({"type": "tool_use", "name": "x", "input": {}})).run()


# ---------- 요청이 서로 섞이지 않는다
def test_two_runs_do_not_share_state():
    first, second = Script(_text("하나")), Script(_calls(_tool_use()), _text("둘"))
    a, b = first.run(), second.run()
    assert (a.answer, a.steps) == ("하나", 1) and (b.answer, b.steps) == ("둘", 2)


# ---------- 랭체인 추적(LangSmith)은 환경과 상관없이 꺼져 있어야 한다(켜지면 질문·도구 결과·답이 외부로 나간다)
@pytest.fixture
def tracer_events(monkeypatch):
    """추적 환경변수를 가짜 키·닫힌 주소로 켤 수 있게 하고, 추적기가 남기려는 이벤트를 센다(네트워크는 쓰지 않는다)."""
    from langchain_core.tracers.langchain import LangChainTracer
    from langsmith import client as langsmith_client
    from langsmith import utils

    def no_network(*args, **kwargs):
        raise RuntimeError("시험에서는 LangSmith 로 요청을 보내지 않는다")

    events: list[str] = []
    monkeypatch.setattr(langsmith_client.Client, "request_with_retries", no_network)
    monkeypatch.setattr(
        LangChainTracer,
        "_persist_run_single",
        lambda self, run: events.append(json.dumps([run.name, run.inputs], default=str)),
    )
    monkeypatch.setattr(
        LangChainTracer,
        "_update_run_single",
        lambda self, run: events.append(json.dumps([run.name, run.outputs], default=str)),
    )

    def clear_caches():
        for fn in (utils.get_env_var, utils.tracing_is_enabled):  # 환경변수 읽기 캐시
            if hasattr(fn, "cache_clear"):
                fn.cache_clear()

    def enable(**env):
        for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("LANGSMITH_API_KEY", "fake-key")
        monkeypatch.setenv("LANGSMITH_ENDPOINT", "http://127.0.0.1:9")  # 닫힌 포트
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        clear_caches()

    yield enable, events
    monkeypatch.undo()
    clear_caches()


TRACING_ENVS = [{"LANGSMITH_TRACING": "true"}, {"LANGCHAIN_TRACING_V2": "true"}]


def _nested_run(question="바깥 질문"):
    """메인 그래프의 tools 노드 안에서 탭 에이전트(run_agent)가 도는 모양."""
    child_replies = iter([_calls(_tool_use("c1", "look", {})), _text("안쪽 답")])

    def handle(calls):
        child = agent.run_agent(
            "안쪽",
            [{"role": "user", "content": "안쪽 질문"}],
            [Tool("look", "d", {}, lambda a: {"v": "도구 결과"})],
            post=lambda body: next(child_replies),
        )
        return tool_graph.ToolRound([(c["id"], child.answer, False) for c in calls])

    return Script(_calls(_tool_use("p1", "ask")), _text("바깥 답"), tool_outputs=handle).run(
        question=question
    )


@pytest.mark.parametrize("env", TRACING_ENVS)
def test_tracing_env_does_not_make_run_graph_emit_trace_events(tracer_events, env):
    enable, events = tracer_events
    enable(**env)
    run = Script(_calls(_tool_use()), _text("답")).run()
    assert run.answer == "답"
    assert events == []


@pytest.mark.parametrize("env", TRACING_ENVS)
def test_tracing_env_does_not_make_nested_run_graph_emit_trace_events(tracer_events, env):
    enable, events = tracer_events
    enable(**env)
    assert _nested_run().answer == "바깥 답"
    assert events == []


@pytest.mark.parametrize("env", TRACING_ENVS)
def test_tracing_env_does_not_make_plan_reminders_emit_trace_events(
    tracer_events, monkeypatch, env
):
    from app.shared.config import settings
    from app.shared.llm import doc_ai, transport

    enable, events = tracer_events
    enable(**env)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(
        transport,
        "post_messages",
        lambda body, *, timeout, retry: {
            "content": [
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "report_reminders",
                    "input": {"reminders": []},
                }
            ]
        },
    )
    assert doc_ai.plan_reminders("제목", "본문", ["2026-11-10"], "2026-11-06") == []
    assert events == []


def test_tracing_env_is_really_on_without_the_protection(tracer_events):
    """보호 없이 그래프를 부르면 이벤트가 생기는 환경인지 확인한다(위 시험이 헛돌지 않는다는 증거)."""
    enable, events = tracer_events
    enable(LANGSMITH_TRACING="true")
    script = Script(_text("답"))
    run = tool_graph.Run(
        model=PostChatModel(post=script.post, llm_model="m", system="시스템"),
        handle=script.handle,
        max_steps=4,
    )
    tool_graph.GRAPH.invoke(
        {"messages": [HumanMessage(content="질문")]}, config={"configurable": {"run": run}}
    )
    assert events


# ---------- 탭 에이전트의 run_graph 는 메인 그래프의 tools 노드 안에서 하위 그래프로 돈다
def _current_run():
    return var_child_runnable_config.get()["configurable"]["run"]


def _parent(handle, *replies, max_steps=4):
    """진짜 메인 그래프(Run 과 handle)를 가짜 post 로 돌린다. (Run, 요청 본문들)을 돌려준다."""
    bodies: list[dict] = []
    it = iter(replies)

    def post(body):
        bodies.append(json.loads(json.dumps(body)))
        return next(it)

    run = tool_graph.Run(
        model=PostChatModel(post=post, llm_model="m", system="바깥"),
        handle=handle,
        max_steps=max_steps,
    )
    tool_graph.run_graph(run, [HumanMessage(content="바깥 질문")])
    return run, bodies


def _child_post(log, *replies):
    it = iter(replies)

    def post(body):
        log.append((threading.get_ident(), json.loads(json.dumps(body))))
        reply = next(it)
        if isinstance(reply, Exception):
            raise reply
        return reply

    return post


def test_nested_agents_see_their_own_run_and_do_not_leak_messages():
    main = threading.get_ident()
    threads: list[int] = []
    seen: dict = {"child_runs": []}
    c1, c2 = [], []

    def handle(calls):
        threads.append(threading.get_ident())
        seen["before"] = _current_run()

        def tool(args):
            threads.append(threading.get_ident())
            seen["child_runs"].append(_current_run())
            return {"안쪽": "하나 결과"}

        first = agent.run_agent(
            "시스템하나",
            [{"role": "user", "content": "하나 질문"}],
            [Tool("look", "d", {}, tool)],
            post=_child_post(c1, _calls(_tool_use("a", "look", {})), _text("하나 답")),
        )
        seen["mid"] = _current_run()
        second = agent.run_agent(
            "시스템둘",
            [{"role": "user", "content": "둘 질문"}],
            [],
            post=_child_post(c2, _text("둘 답")),
        )
        seen["after"] = _current_run()
        threads.append(threading.get_ident())
        seen["answers"] = (first.answer, second.answer)
        text = f"{first.answer}|{second.answer}"
        return tool_graph.ToolRound([(c["id"], text, False) for c in calls])

    run, parent_bodies = _parent(handle, _calls(_tool_use("p1", "ask")), _text("바깥 답"))

    # 각 단계는 호출 전후에 자기 Run 을 본다(자식의 Run 으로 바뀌어 있지 않다)
    assert seen["before"] is run and seen["mid"] is run and seen["after"] is run
    assert len(seen["child_runs"]) == 1 and seen["child_runs"][0] is not run
    assert run.answer == "바깥 답" and run.steps == 2
    assert seen["answers"] == ("하나 답", "둘 답")
    # 부모·자식·자식 사이에 메시지가 새지 않는다
    parent_text = json.dumps(parent_bodies, ensure_ascii=False)
    assert "하나 질문" not in parent_text and "둘 질문" not in parent_text
    assert "하나 답|둘 답" in parent_text  # 부모는 도구 결과로만 안다
    first_text = json.dumps([b for _, b in c1], ensure_ascii=False)
    second_text = json.dumps([b for _, b in c2], ensure_ascii=False)
    assert "바깥 질문" not in first_text and "둘 질문" not in first_text
    assert "바깥 질문" not in second_text and "하나" not in second_text
    assert len(c1) == 2 and len(c2) == 1
    # 모든 노드와 모델 호출이 호출한 스레드에서 돈다
    assert set(threads) == {main}
    assert {t for t, _ in c1 + c2} == {main}


def test_child_step_limit_is_its_own_and_not_inherited_from_the_parent():
    outcome: dict = {}

    def handle(calls):
        # 부모 반복 상한(50)보다 많은 노드가 필요한 자식: 부모의 상한을 물려받으면 GraphRecursionError 가 난다
        try:
            agent.run_agent(
                "자식",
                [{"role": "user", "content": "q"}],
                [Tool("look", "d", {}, lambda a: {})],
                post=lambda body: _calls(_tool_use("x", "look", {})),
                max_steps=40,
            )
        except Exception as e:  # noqa: BLE001 - 어떤 예외가 나는지가 시험 대상이다
            outcome["error"] = e
        outcome["limit_after"] = var_child_runnable_config.get()["recursion_limit"]
        return tool_graph.ToolRound([(c["id"], "{}", False) for c in calls])

    run, _ = _parent(handle, _calls(_tool_use("p1", "ask")), _text("끝"))
    assert isinstance(outcome["error"], LLMUnavailable)
    assert "정해진 횟수" in str(outcome["error"])
    assert outcome["limit_after"] == 50  # 부모의 상한은 그대로
    assert run.answer == "끝"


def test_an_error_in_a_nested_agent_reaches_the_parent_as_the_same_type():
    class ChildBoom(RuntimeError):
        pass

    def handle(calls):
        agent.run_agent(
            "자식",
            [{"role": "user", "content": "q"}],
            [],
            post=_child_post([], ChildBoom("자식 실패")),
        )
        return tool_graph.ToolRound([])

    with pytest.raises(ChildBoom):
        _parent(handle, _calls(_tool_use("p1", "ask")))
