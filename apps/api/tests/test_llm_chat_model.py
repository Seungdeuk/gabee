"""`shared/llm/chat_model.py`: 우리 `post` 를 랭체인 채팅 모델로 감싸는 어댑터. 요청 본문은 예전 메인 루프가 만들던 것과 같아야 한다."""

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.shared.llm import chat_model
from app.shared.llm.chat_model import (
    PostChatModel,
    from_anthropic_reply,
    text_of,
    to_anthropic_messages,
    to_langchain_messages,
)

TOOL_USE = {
    "type": "tool_use",
    "id": "toolu_1",
    "name": "search_knowledge",
    "input": {"query": "전기"},
}


# ---------- 메시지 변환
def test_plain_turns_become_role_content_pairs():
    messages = [HumanMessage(content="안녕"), AIMessage(content="네"), HumanMessage(content="질문")]
    assert to_anthropic_messages(messages) == [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": "네"},
        {"role": "user", "content": "질문"},
    ]


def test_assistant_tool_blocks_are_sent_back_unchanged():
    blocks = [{"type": "text", "text": "찾아볼게요"}, TOOL_USE, {"type": "x-extra", "keep": True}]
    out = to_anthropic_messages([HumanMessage(content="q"), AIMessage(content=blocks)])
    assert out[1] == {"role": "assistant", "content": blocks}  # 모르는 블록도 그대로


def test_consecutive_tool_messages_merge_into_one_user_message():
    messages = [
        HumanMessage(content="q"),
        AIMessage(content=[TOOL_USE]),
        ToolMessage(content='{"a": 1}', tool_call_id="toolu_1"),
        ToolMessage(content='{"error": "x"}', tool_call_id="toolu_2", status="error"),
        HumanMessage(content="다음"),
    ]
    out = to_anthropic_messages(messages)
    assert out[2] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_1",
                "content": '{"a": 1}',
                "is_error": False,
            },
            {
                "type": "tool_result",
                "tool_use_id": "toolu_2",
                "content": '{"error": "x"}',
                "is_error": True,
            },
        ],
    }
    assert out[3] == {"role": "user", "content": "다음"} and len(out) == 4


def test_system_messages_are_left_out_and_unknown_types_are_refused():
    assert to_anthropic_messages([SystemMessage(content="규칙"), HumanMessage(content="q")]) == [
        {"role": "user", "content": "q"}
    ]
    with pytest.raises(ValueError):
        to_anthropic_messages([object()])  # type: ignore[list-item]


def test_history_dicts_become_langchain_messages_and_back():
    history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    assert to_anthropic_messages(to_langchain_messages(history)) == history


# ---------- 응답 변환
def test_text_reply():
    message = from_anthropic_reply(
        {
            "content": [{"type": "text", "text": " 안녕 "}],
            "usage": {"input_tokens": 5, "output_tokens": 2},
        }
    )
    assert message.tool_calls == [] and text_of(message) == "안녕"
    assert message.usage_metadata == {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}


def test_tool_use_blocks_become_tool_calls_and_stay_in_content():
    reply = {
        "content": [{"type": "text", "text": "잠깐"}, TOOL_USE],
        "model": "m",
        "stop_reason": "tool_use",
    }
    message = from_anthropic_reply(reply)
    assert message.tool_calls == [
        {
            "type": "tool_call",
            "id": "toolu_1",
            "name": "search_knowledge",
            "args": {"query": "전기"},
        }
    ]
    assert message.content == reply["content"]
    assert message.response_metadata == {"model": "m", "stop_reason": "tool_use"}


def test_missing_input_means_empty_args_and_missing_usage_means_zero():
    message = from_anthropic_reply(
        {"content": [{"type": "tool_use", "id": "t", "name": "list_items"}]}
    )
    assert message.tool_calls[0]["args"] == {}
    assert message.usage_metadata["total_tokens"] == 0


@pytest.mark.parametrize(
    "broken", [{"type": "tool_use", "name": "x"}, {"type": "tool_use", "id": "t"}]
)
def test_a_tool_use_without_id_or_name_raises_key_error(broken):
    """예전 루프도 KeyError 였고 호출한 쪽(rag_chat.ask)이 대체 답으로 바꾼다."""
    with pytest.raises(KeyError):
        from_anthropic_reply({"content": [broken]})


@pytest.mark.parametrize(
    "content,expected",
    [
        ("그냥 글", "그냥 글"),
        (
            [
                {"type": "text", "text": "가"},
                {"type": "tool_use", "id": "t", "name": "n"},
                {"type": "text", "text": "나"},
            ],
            "가나",
        ),
        ([], ""),
    ],
)
def test_text_of(content, expected):
    assert text_of(AIMessage(content=content)) == expected


# ---------- 채팅 모델
def test_request_body_has_exactly_the_keys_the_old_loop_sent():
    seen: list[dict] = []

    def post(body):
        seen.append(body)
        return {
            "content": [{"type": "text", "text": "답"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    tools = [{"name": "t", "description": "d", "input_schema": {"type": "object"}}]
    model = PostChatModel(
        post=post, llm_model="claude-x", max_tokens=1024, system="시스템", tools=tools
    )
    reply = model.invoke([HumanMessage(content="질문")])
    assert text_of(reply) == "답"
    assert seen == [
        {
            "model": "claude-x",
            "max_tokens": 1024,
            "system": "시스템",
            "tools": tools,
            "messages": [{"role": "user", "content": "질문"}],
            # 옛 루프의 키에 더해, 도구 루프가 앞 내용을 다시 보내는 비용을 줄이려고 자동 캐시를 켠다(chat_model.py, #371)
            "cache_control": {"type": "ephemeral"},
        }
    ]


def test_failures_from_post_pass_through_unchanged():
    def post(body):
        raise httpx.ConnectError("boom")

    with pytest.raises(httpx.ConnectError):
        PostChatModel(post=post, llm_model="m").invoke([HumanMessage(content="q")])


def test_instances_do_not_share_the_default_tool_list():
    a = PostChatModel(post=lambda b: {}, llm_model="m")
    b = PostChatModel(post=lambda b: {}, llm_model="m")
    a.tools.append({"name": "x"})
    assert b.tools == []


def test_module_exports_what_the_graph_needs():
    assert callable(chat_model.text_of) and callable(chat_model.to_langchain_messages)
