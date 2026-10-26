from datetime import datetime

from pydantic import BaseModel, Field


class PinCreate(BaseModel):
    room_id: str | None = Field(None, max_length=32, description="대화방 id. 없으면 가족 전체방")
    message_id: int = Field(..., ge=1)


class PinItem(BaseModel):
    message_id: int
    text: str  # 메시지 본문(길면 앞 200자)
    text_truncated: bool  # 본문을 잘랐으면 true(말줄임 표시는 붙이지 않는다)
    user_id: str  # 메시지를 쓴 사람
    user_name: str
    created_at: datetime  # 메시지를 보낸 시각
    pinned_by: str  # 고정한 사람
    pinned_by_name: str
    pinned_at: datetime


class PinsOut(BaseModel):
    items: list[PinItem]  # 고정 시각 최신순, 최대 2개


class PinResult(BaseModel):
    item: PinItem
    replaced_message_id: int | None  # 최대 개수 때문에 자동 해제된 가장 오래된 고정의 메시지 id
    already_pinned: bool  # 이미 고정돼 있어 그대로 둔 경우 true
