"""PostChatModel 이 첫 호출 강제 도구 사용·마지막 호출 도구 금지를 요청 본문에 옮기는지 확인한다."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.shared.llm.chat_model import LAST_CALL_NOTE, PostChatModel


def _model(bodies, name="claude-haiku-5-5"):
    def post(body):
        bodies.append(body)
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}]}

    return PostChatModel(post=post, llm_model=name, tools=[{"name": "t"}])


def test_force_tool_sets_tool_choice_any():
    bodies = []
    _model(bodies).invoke([HumanMessage(content="질문")], force_tool=True)
    assert bodies[0]["tool_choice"] == {"type": "any"}


def test_plain_call_has_no_tool_choice():
    bodies = []
    _model(bodies).invoke([HumanMessage(content="질문")])
    assert "tool_choice" not in bodies[0]


def test_forced_tool_use_is_skipped_for_models_that_reject_it():
    for name in ("claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-mythos-5-1"):
        bodies = []
        _model(bodies, name).invoke([HumanMessage(content="질문")], force_tool=True)
        assert "tool_choice" not in bodies[0]


def test_last_call_forbids_tools_and_asks_for_a_written_answer():
    bodies = []
    call = AIMessage(
        content=[{"type": "tool_use", "id": "t1", "name": "t", "input": {}}],
        tool_calls=[{"type": "tool_call", "id": "t1", "name": "t", "args": {}}],
    )
    messages = [HumanMessage(content="질문"), call, ToolMessage(content="{}", tool_call_id="t1")]
    _model(bodies).invoke(messages, no_tools=True)
    assert bodies[0]["tool_choice"] == {"type": "none"}
    last = bodies[0]["messages"][-1]["content"]
    assert last[0]["type"] == "tool_result" and last[-1] == {"type": "text", "text": LAST_CALL_NOTE}
    assert bodies[0]["messages"][0] == {"role": "user", "content": "질문"}  # 앞 대화는 그대로


def test_answer_cut_by_max_tokens_is_marked_as_cut():
    from app.shared.llm import tool_graph

    def post(body):
        return {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "## 고령"}]}

    model = PostChatModel(post=post, llm_model="claude-haiku-5-5", tools=[{"name": "t"}])
    run = tool_graph.Run(model=model, handle=lambda calls: tool_graph.ToolRound([]), max_steps=3)
    tool_graph.run_graph(run, [HumanMessage(content="질문")])
    assert run.answer.startswith("## 고령")
    assert run.answer.endswith(tool_graph.TRUNCATED_NOTE)
    assert run.steps == 1  # 호출을 늘리지 않는다
