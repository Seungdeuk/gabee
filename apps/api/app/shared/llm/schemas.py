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


class ProposalOut(BaseModel):
    """에이전트가 제안한 쓰기 동작. 사용자가 확인하면 `POST /<tab>/agent/confirm` 에 token 을 보낸다."""

    token: str
    summary: str  # 서버가 만든 요약문(예: "지출 등록: 치과 50,000원 ...")
    tab: Literal["billing", "care"]


class AgentChatOut(BaseModel):
    reply: str
    source: Literal["ai", "fallback"]  # fallback: AI 연결이 꺼져 있거나 담당 에이전트가 답하지 못함
    tool_calls: list[str]  # 이번 답을 만들며 에이전트가 부른 도구 이름(확인용)
    proposals: list[ProposalOut] = []  # 사용자가 확인해야 실행되는 쓰기 제안


class AgentConfirmIn(BaseModel):
    token: str = Field(min_length=10, max_length=4000)


class AgentConfirmOut(BaseModel):
    ok: bool
    summary: str
