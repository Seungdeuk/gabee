from datetime import datetime

from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class MessageOut(BaseModel):
    id: int
    user_id: str
    user_name: str
    text: str
    created_at: datetime


class ReadMark(BaseModel):
    message_id: int = Field(ge=1, le=2**31 - 1)


class ReadPosition(BaseModel):
    last_read_message_id: int


class ReadStateOut(BaseModel):
    user_id: str
    last_read_message_id: int


class UnreadOut(BaseModel):
    unread: int
    last_read_message_id: int
