from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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


class PhotoOut(BaseModel):
    id: str
    filename: str
    size: int
    status: str
    created_at: datetime
