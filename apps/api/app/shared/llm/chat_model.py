"""우리 `post` 함수(Anthropic Messages API 요청 → 응답 딕셔너리)를 랭체인 채팅 모델로 감싼다.

랭그래프 같은 랭체인 도구가 모델을 부를 수 있게 하되, 실제 호출은 지금처럼 `post` 가 한다(운영은 `transport.post_messages`,
시험은 가짜 `post`). 그래서 호출 수 집계(`ai_guard`)·재시도 정책·시험이 모델을 가짜로 바꾸는 자리가 그대로 유지된다.
나중에 `ChatAnthropic` 으로 바꿀 때도 이 클래스 한 자리만 바꾸면 된다.

변환 규칙(요청 본문은 예전 메인 루프가 만들던 것과 같다):
- 첫 머리의 `system`·`tools`·`model`·`max_tokens` 는 필드로 들고, 메시지는 `{"role", "content"}` 로 바꾼다.
- 도구 호출 응답은 Anthropic 이 준 `content` 블록 목록을 **그대로** AIMessage.content 에 담아 두고(다음 요청에 그대로 돌려보낸다),
  도구 호출은 `tool_calls` 에도 풀어 둔다.
- 연이은 ToolMessage 는 `tool_result` 블록 여러 개를 가진 user 메시지 하나로 합친다."""

import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult

from . import transport


def to_anthropic_messages(messages: list[BaseMessage]) -> list[dict]:
    """랭체인 메시지를 Anthropic Messages API 의 `messages` 로 바꾼다(SystemMessage 는 `system` 으로 가므로 뺀다)."""
    out: list[dict] = []
    results: list[dict] = []

    def flush() -> None:
        if results:
            out.append({"role": "user", "content": list(results)})
            results.clear()

    for message in messages:
        if isinstance(message, SystemMessage):
            continue
        if isinstance(message, ToolMessage):
            content = message.content
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": content
                    if isinstance(content, str)
                    else json.dumps(content, ensure_ascii=False),
                    "is_error": message.status == "error",
                }
            )
            continue
        flush()
        if isinstance(message, HumanMessage):
            out.append({"role": "user", "content": message.content})
        elif isinstance(message, AIMessage):
            out.append({"role": "assistant", "content": message.content})
        else:
            raise ValueError(f"지원하지 않는 메시지 종류예요: {type(message).__name__}")
    flush()
    return out


def to_langchain_messages(messages: list[dict]) -> list[BaseMessage]:
    """`{"role", "content"}` 목록(앞 대화 + 질문)을 랭체인 메시지로 바꾼다. 글 내용만 있는 user·assistant 턴용이다."""
    return [
        HumanMessage(content=m["content"])
        if m["role"] == "user"
        else AIMessage(content=m["content"])
        for m in messages
    ]


def from_anthropic_reply(reply: dict) -> AIMessage:
    """Anthropic 응답 딕셔너리를 AIMessage 로 바꾼다. content 블록은 원본 그대로 둔다."""
    content = reply.get("content") or []
    calls = [
        {
            "type": "tool_call",
            "id": block["id"],
            "name": block["name"],
            "args": block.get("input") or {},
        }
        for block in content
        if block.get("type") == "tool_use"
    ]
    tokens_in, tokens_out = transport.usage_of(reply)
    return AIMessage(
        content=content,
        tool_calls=calls,
        usage_metadata={
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "total_tokens": tokens_in + tokens_out,
        },
        response_metadata={"model": reply.get("model"), "stop_reason": reply.get("stop_reason")},
    )


def text_of(message: AIMessage) -> str:
    """AIMessage 의 글 블록을 이어 붙인 답(앞뒤 공백 제거). 글 블록이 없으면 빈 문자열."""
    content = message.content
    if isinstance(content, str):
        return content.strip()
    return "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()


class PostChatModel(BaseChatModel):
    """`post(body) -> reply` 를 부르는 채팅 모델. 도구 정의(`tools`)는 Anthropic 형식(이름·설명·input_schema) 그대로다."""

    post: Any
    llm_model: str
    max_tokens: int = 1024
    system: str = ""
    tools: list[dict] = []

    @property
    def _llm_type(self) -> str:
        return "gabee-post"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        body = {
            "model": self.llm_model,
            "max_tokens": self.max_tokens,
            "system": self.system,
            "tools": self.tools,
            "messages": to_anthropic_messages(messages),
        }
        message = from_anthropic_reply(self.post(body))
        return ChatResult(generations=[ChatGeneration(message=message)])
