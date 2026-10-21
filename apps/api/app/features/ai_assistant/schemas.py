from datetime import datetime

from pydantic import BaseModel, Field


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatOut(BaseModel):
    reply: str
    source: str  # ai: AI 가 답함 | fallback: AI 를 쓸 수 없어 기본 안내를 보냄


class PhotoOut(BaseModel):
    id: str
    filename: str
    size: int
    status: str
    created_at: datetime
