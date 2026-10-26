import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


class LinkCreate(BaseModel):
    room_id: str | None = Field(None, max_length=32, description="대화방 id. 없으면 가족 전체방")
    message_id: int = Field(..., ge=1, le=2**31 - 1)
    kind: Literal["event", "todo"]
    target_id: str = Field(..., min_length=1, max_length=32, description="일정 또는 할 일 id")
    title: str = Field(..., max_length=200, description="등록한 제목 복사본(공백 정리 후 1~120자)")
    date: dt.date | None = None
    time: str | None = Field(None, pattern=TIME_PATTERN, description="HH:MM")


class LinkOut(BaseModel):
    id: str
    room_id: str
    message_id: int
    kind: Literal["event", "todo"]
    target_id: str
    title: str  # 등록 시점의 복사본
    date: dt.date | None
    time: str | None  # HH:MM
    created_by: str
    created_by_name: str
    created_at: dt.datetime
    message_text: str  # 원본 메시지 본문 앞 100자(조회할 때 messages 와 join)
    message_user_name: str  # 원본 메시지를 쓴 사람


class LinksOut(BaseModel):
    items: list[LinkOut]  # 최신순
