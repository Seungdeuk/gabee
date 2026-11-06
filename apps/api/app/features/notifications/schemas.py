"""알림함 API 요청·응답 모델."""

from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.shared.notifications import KINDS, PUSH_KINDS

Kind = Literal[*KINDS]
PushKind = Literal[*PUSH_KINDS]
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
    muted_kinds: list[PushKind] = []
    quiet_start: time | None = None
    quiet_end: time | None = None

    @model_validator(mode="after")
    def _quiet_hours_pair(self) -> "PushSettingsIn":
        if (self.quiet_start is None) != (self.quiet_end is None):
            raise ValueError("방해금지 시작과 끝 시간은 함께 정해야 해요")
        return self


class PushSettingsOut(PushSettingsIn):
    pass


_TOKEN_PREFIXES = ("ExponentPushToken[", "ExpoPushToken[")


def _check_token(value: str) -> str:
    if not (value.startswith(_TOKEN_PREFIXES) and value.endswith("]") and len(value) <= 255):
        raise ValueError("푸시 토큰 형식이 올바르지 않아요")
    return value


class PushTokenIn(BaseModel):
    """기기의 Expo 푸시 토큰 등록 요청."""

    token: str
    platform: Literal["android", "ios"]
    device_label: str | None = Field(default=None, max_length=80)

    _token_ok = field_validator("token")(_check_token)


class PushTokenDelete(BaseModel):
    """푸시 토큰 해제 요청(로그아웃 때)."""

    token: str
