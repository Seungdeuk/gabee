from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class EventCreate(BaseModel):
    """시각은 두 방식 중 하나로 준다. 새 방식은 start_date(+ start_time, end_time),
    옛 방식은 starts_at. 둘 다 오면 start_date 를 쓴다. 메모도 memo 가 note 의 새 이름이다.
    share_with 에 든 가족 구성원마다 그 사람 몫의 복사본이 생기고, 비워 두면 나만 가진다."""

    title: str = Field(min_length=1, max_length=120)
    starts_at: datetime | None = None
    start_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    note: str = ""
    memo: str | None = None
    status: Literal["pending", "confirmed"] = "confirmed"
    source: Literal["manual", "chat", "photo", "request"] = "manual"
    kind: Literal[1, 2] = 1  # 1 약속 · 2 할 일
    place: str = Field(default="", max_length=200)
    who_ids: list[str] = Field(default_factory=list, max_length=20)  # 관련된 사람
    share_with: list[str] = Field(default_factory=list, max_length=20)
    topic_id: str | None = None  # 내 주제. 공유 복사본에는 붙지 않는다(받는 사람이 직접 붙인다)

    @model_validator(mode="after")
    def _needs_when(self) -> "EventCreate":
        if self.starts_at is None and self.start_date is None:
            raise ValueError("starts_at 또는 start_date 가 필요해요")
        return self


class EventUpdate(BaseModel):
    """바꿀 값만 보낸다. 보내지 않은 값은 그대로 둔다. 시간(start_time·end_time)은 null 로 보내면 지운다(시간 없음).
    공유 대상은 고칠 수 없다(공유는 만들 때만, 복사본은 받은 사람의 일정이다)."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    start_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    kind: Literal[1, 2] | None = None
    place: str | None = Field(default=None, max_length=200)
    memo: str | None = None
    who_ids: list[str] | None = Field(default=None, max_length=20)
    topic_id: str | None = None  # null 로 보내면 주제를 뗀다


class EventOut(BaseModel):
    id: str
    title: str
    starts_at: datetime
    note: str
    status: str
    source: str
    created_by: str
    user_id: str | None
    kind: int
    who_ids: list[str]
    place: str
    start_date: date | None
    start_time: time | None
    end_time: time | None
    memo: str
    checked: bool
    origin_id: str | None
    topic_id: str | None
    edited_at: datetime | None


class SharingOut(BaseModel):
    """누가 이 일정을 나에게 공유했는지(복사본일 때), 원본에서 누구에게 나눠졌는지."""

    shared_by: str | None
    shared_with: list[str]


class CheckBody(BaseModel):
    """확인(약속)·완료(할 일) 표시. 같은 값을 다시 보내도 그대로다."""

    checked: bool


class TopicCreate(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    color: Literal["rose", "amber"]  # constants.TOPIC_COLORS

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("주제 이름이 비었어요")
        return v


class TopicOut(BaseModel):
    id: str
    name: str
    color: str
    created_at: datetime
