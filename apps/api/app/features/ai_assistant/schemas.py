from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.shared.llm.schemas import ProposalOut


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=10)  # 앞 대화(오래된 것부터)


class ChatSource(BaseModel):
    """답이 근거로 쓴 기록. n 은 앱 출처 칩의 번호(1부터)."""

    n: int
    title: str
    item_id: str | None = None
    source_path: str | None = None


class ChatOut(BaseModel):
    reply: str
    source: str  # ai: AI 가 답함 | fallback: AI 를 쓸 수 없어 기본 안내를 보냄
    sources: list[ChatSource] = []
    proposals: list[
        ProposalOut
    ] = []  # 정산·돌봄 에이전트가 제안한 쓰기. 사용자가 확인해야 실행된다


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    size: int
    status: str  # received | analyzed | needs_review | failed


class FileStatusOut(FileOut):
    title: str | None = None
    kind_label: str | None = None
    description: str | None = None
    message: str | None = None
    doubts: list[str] = []  # 글자 인식이 흐려서 사용자에게 맞는지 물어볼 줄(가려진 상태의 글)


class PhotoOut(BaseModel):
    id: str
    filename: str
    size: int
    status: str
    created_at: datetime
