from datetime import datetime

from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    room_id: str | None = Field(default=None, max_length=32)  # 없으면 가족 전체방


class AttachmentOut(BaseModel):
    id: str
    kind: str  # 지금은 image 만
    url: str  # 원본(최대 1600px JPEG) 경로. 로그인이 필요하다
    thumb_url: str  # 목록용 작은 그림 경로
    width: int
    height: int


class MessageOut(BaseModel):
    id: int
    user_id: str
    user_name: str
    text: str  # 사진 메시지는 빈 문자열
    created_at: datetime
    attachment: AttachmentOut | None = None


class ReadMark(BaseModel):
    message_id: int = Field(ge=1, le=2**31 - 1)
    room_id: str | None = Field(default=None, max_length=32)  # 없으면 가족 전체방


class ReadPosition(BaseModel):
    last_read_message_id: int


class ReadStateOut(BaseModel):
    user_id: str
    last_read_message_id: int


class UnreadOut(BaseModel):
    unread: int
    last_read_message_id: int


class RoomOut(BaseModel):
    id: str
    kind: str  # family(가족 전체방) | direct(1:1)
    peer_user_id: str | None  # 1:1 방의 상대, 가족 전체방은 null
    last_message: MessageOut | None
    unread: int


class DirectRoomCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=32)
