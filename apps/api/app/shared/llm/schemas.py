"""탭 에이전트와 직접 대화하는 엔드포인트(POST /<탭>/agent/chat)의 요청·응답."""

from typing import Literal

from pydantic import BaseModel, Field


class AgentChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class AgentChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[AgentChatTurn] = Field(
        default_factory=list, max_length=10
    )  # 앞 대화(오래된 것부터)


class AgentChatOut(BaseModel):
    reply: str
    source: Literal["ai", "fallback"]  # fallback: AI 연결이 꺼져 있거나 담당 에이전트가 답하지 못함
    tool_calls: list[str]  # 이번 답을 만들며 에이전트가 부른 도구 이름(확인용)
