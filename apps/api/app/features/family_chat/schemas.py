from datetime import date, datetime
from typing import Literal

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
    is_assistant: bool = False  # 가비가 @가비 호출에 답해 올린 메시지(앱이 말풍선을 따로 그린다)
    deleted: bool = False  # 보낸 사람이 지운 메시지. text 는 빈 문자열, attachment 는 null 이고 앱은 "삭제된 메시지입니다"를 보인다


class DeletedOut(BaseModel):
    message_ids: list[int]  # since 이후에 지워진 메시지 id(지운 순서, 최대 200개)
    server_time: datetime  # 이 응답을 만든 서버 시각. 다음 조회의 since 로 쓴다


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


class TodoCreate(BaseModel):
    """created_by 같은 값은 받지 않는다(로그인한 사용자에서 유도)."""

    title: str = Field(min_length=1, max_length=120)
    assignee_id: str | None = Field(default=None, max_length=32)
    due_date: date | None = None
    source: Literal["manual", "chat"] = "manual"


class TodoUpdate(BaseModel):
    """보낸 항목만 바꾼다. assignee_id·due_date 에 null 을 보내면 비운다. done 은 완료(true)·되돌리기(false)."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    assignee_id: str | None = Field(default=None, max_length=32)
    due_date: date | None = None
    done: bool | None = None


class TodoOut(BaseModel):
    id: str
    title: str
    assignee_id: str | None
    due_date: date | None
    done: bool
    done_at: datetime | None
    done_by: str | None
    created_by: str
    source: str
    created_at: datetime
