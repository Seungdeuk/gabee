"""메인 AI 채팅의 도구 반복 루프(`knowledge/rag_graph.py`, 랭그래프): 흐름·반복 상한·직통 응답·오류 전달."""

import httpx
import pytest
from langchain_core.messages import HumanMessage

from app.features.ai_assistant.knowledge import rag_graph
from app.shared.llm.chat_model import PostChatModel


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
        return rag_graph.ToolRound([(c["id"], '{"ok": true}', False) for c in calls])

    def run(self, max_steps=4, question="질문"):
        model = PostChatModel(post=self.post, llm_model="m", system="시스템")
        run = rag_graph.Run(model=model, handle=self.handle, max_steps=max_steps)
        return rag_graph.run_chat(run, [HumanMessage(content=question)])


# ---------- 흐름
def test_graph_has_the_expected_nodes_and_edges():
    graph = rag_graph.GRAPH.get_graph()
    assert set(graph.nodes) == {"__start__", "mask", "model", "tools", "restore", "__end__"}
    edges = {(e.source, e.target) for e in graph.edges}
    assert edges == {
        ("__start__", "mask"),
        ("mask", "model"),
        ("model", "tools"),
        ("model", "restore"),
        ("tools", "model"),
        ("tools", "restore"),
        ("restore", "__end__"),
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
        return rag_graph.ToolRound([(calls[0]["id"], '{"error": "없어요"}', True)])

    script = Script(_calls(_tool_use()), _text("못 찾았어요"), tool_outputs=outputs)
    script.run()
    (result,) = script.bodies[1]["messages"][2]["content"]
    assert result["is_error"] is True and "없어요" in result["content"]


# ---------- 가리기·되돌리기 훅
def test_mask_is_applied_to_the_question_and_history_before_the_model_sees_them():
    script = Script(_text("답"))
    model = PostChatModel(post=script.post, llm_model="m")
    run = rag_graph.Run(
        model=model,
        handle=script.handle,
        max_steps=4,
        mask=lambda text: text.replace("수진", "[P1]"),
    )
    rag_graph.run_chat(run, [HumanMessage(content="수진이 병원"), HumanMessage(content="수진 약")])
    assert [m["content"] for m in script.bodies[0]["messages"]] == ["[P1]이 병원", "[P1] 약"]


def test_restore_is_applied_to_the_models_final_answer_only():
    script = Script(_text("[P1]에게 연락하세요"))
    model = PostChatModel(post=script.post, llm_model="m")
    run = rag_graph.Run(
        model=model,
        handle=script.handle,
        max_steps=4,
        restore=lambda text: text.replace("[P1]", "수진"),
    )
    rag_graph.run_chat(run, [HumanMessage(content="q")])
    assert run.answer == "수진에게 연락하세요"
    # 모델에게 가는 요청에는 되돌리기가 적용되지 않는다(이름표 그대로)
    assert script.bodies[0]["messages"][0]["content"] == "q"


def test_direct_answers_are_not_restored_because_they_are_real_text():
    def outputs(calls):
        return rag_graph.ToolRound([(calls[0]["id"], "{}", False)], direct_answer="[P1] 그대로")

    seen = []
    script = Script(
        _calls(_tool_use(name="ask_care", args={"question": "q"})), tool_outputs=outputs
    )
    model = PostChatModel(post=script.post, llm_model="m")
    run = rag_graph.Run(
        model=model, handle=script.handle, max_steps=4, restore=lambda t: seen.append(t) or "바뀜"
    )
    rag_graph.run_chat(run, [HumanMessage(content="q")])
    assert run.answer == "[P1] 그대로" and seen == []


def test_restore_is_skipped_when_there_is_no_answer():
    seen = []
    script = Script(_calls(_tool_use()))  # 반복 상한까지 도구만 부른다
    model = PostChatModel(post=script.post, llm_model="m")
    run = rag_graph.Run(
        model=model, handle=script.handle, max_steps=2, restore=lambda t: seen.append(t) or t
    )
    rag_graph.run_chat(run, [HumanMessage(content="q")])
    assert run.answer == "" and seen == []


# ---------- 직통 응답
def test_direct_answer_ends_the_loop_without_calling_the_model_again():
    def outputs(calls):
        return rag_graph.ToolRound([(calls[0]["id"], "{}", False)], direct_answer="에이전트의 답")

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


# ---------- 랭체인 추적은 꺼져 있어야 한다(켜지면 프롬프트와 가족 정보가 외부로 나간다)
def test_langsmith_tracing_is_off(monkeypatch):
    from langsmith import utils

    for name in (
        "LANGSMITH_TRACING",
        "LANGCHAIN_TRACING_V2",
        "LANGSMITH_API_KEY",
        "LANGCHAIN_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    utils.tracing_is_enabled.cache_clear() if hasattr(
        utils.tracing_is_enabled, "cache_clear"
    ) else None
    assert not utils.tracing_is_enabled()
    Script(
        _text("추적 없이")
    ).run()  # 그래프를 돌려도 외부로 나가지 않는다(네트워크 대신 가짜 post 만 쓴다)
