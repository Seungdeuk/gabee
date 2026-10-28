"""알림함 API 요청·응답 모델."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.shared.notifications import KINDS

Kind = Literal[*KINDS]


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    event: str
    title: str
    body: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    actor_user_id: str | None = None
    created_at: datetime
    read_at: datetime | None = None


class NotificationList(BaseModel):
    items: list[NotificationOut]
    next_cursor: str | None = None


class UnreadCount(BaseModel):
    total: int
    by_kind: dict[str, int]


class ReadAllBody(BaseModel):
    kind: Kind | None = None


class ReadAllResult(BaseModel):
    updated: int
