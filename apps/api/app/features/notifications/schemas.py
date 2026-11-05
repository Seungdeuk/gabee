"""알림함 API 요청·응답 모델."""

from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.shared.notifications import KINDS

Kind = Literal[*KINDS]
PreviewMode = Literal["full", "sender", "hidden"]


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


class PushSettingsIn(BaseModel):
    """푸시 설정 저장 요청. 방해금지 시작·끝은 둘 다 있거나 둘 다 없어야 한다."""

    enabled: bool = True
    preview_mode: PreviewMode = "full"
    muted_kinds: list[Kind] = []
    quiet_start: time | None = None
    quiet_end: time | None = None

    @model_validator(mode="after")
    def _quiet_hours_pair(self) -> "PushSettingsIn":
        if (self.quiet_start is None) != (self.quiet_end is None):
            raise ValueError("방해금지 시작과 끝 시간은 함께 정해야 해요")
        return self


class PushSettingsOut(PushSettingsIn):
    pass
