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
    share_with: list[str] = Field(default_factory=list, max_length=20)
    topic_id: str | None = None  # 내 주제. 공유 복사본에는 붙지 않는다(받는 사람이 직접 붙인다)
    suggestion_id: str | None = None  # 추천에서 등록할 때 그 제안의 id(내 대기 제안만, 아니면 400)

    @model_validator(mode="after")
    def _needs_when(self) -> "EventCreate":
        if self.starts_at is None and self.start_date is None:
            raise ValueError("starts_at 또는 start_date 가 필요해요")
        return self


class EventUpdate(BaseModel):
    """바꿀 값만 보낸다. 보내지 않은 값은 그대로 둔다. 시간(start_time·end_time)은 null 로 보내면 지운다(시간 없음).
    share_with 는 공유 대상 전체를 다시 정한다(원본 주인만, 아니면 403 not_share_owner). 새로 든 사람에게는 복사본이 생기고,
    빠진 사람의 복사본은 지워진다. 보내지 않으면 공유는 그대로다."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    start_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    kind: Literal[1, 2] | None = None
    place: str | None = Field(default=None, max_length=200)
    memo: str | None = None
    topic_id: str | None = None  # null 로 보내면 주제를 뗀다
    share_with: list[str] | None = Field(default=None, max_length=20)


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
    place: str
    start_date: date | None
    start_time: time | None
    end_time: time | None
    memo: str
    checked: bool
    origin_id: str | None
    topic_id: str | None
    edited_at: datetime | None
    # 공동 정보(저장하지 않고 계산): 나와 얽힌 사람(공유한 사람·받은 사람·부탁한 사람, 나 제외)과 공동 일정인가
    shared_ids: list[str] = Field(default_factory=list)
    shared: bool = False


class SharingOut(BaseModel):
    """누가 이 일정을 나에게 공유했는지(복사본일 때), 원본에서 누구에게 나눠졌는지."""

    shared_by: str | None
    shared_with: list[str]


class CheckBody(BaseModel):
    """확인(약속)·완료(할 일) 표시. 같은 값을 다시 보내도 그대로다."""

    checked: bool


class TopicCreate(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    color: Literal["rose", "amber", "green", "sky", "purple"]  # constants.TOPIC_COLORS

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


class RequestCreate(BaseModel):
    """같이해요 부탁 보내기. to_ids 는 같은 가족 구성원이어야 하고 나는 뺀다(중복은 하나로)."""

    title: str = Field(min_length=1, max_length=120)
    start_date: date
    start_time: time | None = None
    end_time: time | None = None
    place: str = Field(default="", max_length=200)
    memo: str = Field(default="", max_length=2000)
    to_ids: list[str] = Field(min_length=1, max_length=20)

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("제목이 비었어요")
        return v


class RequestAnswer(BaseModel):
    """받은 부탁에 답한다. 수락(accepted)이면 어떤 일정으로 만들지 kind(1 약속·2 할 일)가 필요하다."""

    answer: Literal["accepted", "declined"]
    kind: Literal[1, 2] | None = None


class RequestRecipients(BaseModel):
    """부탁의 받는 사람을 바꾼 뒤의 전체 목록. 보낸 사람만 바꿀 수 있고, 최소 1명이며 나는 뺀다."""

    to_ids: list[str] = Field(min_length=1, max_length=20)


class RequestMemo(BaseModel):
    """부탁의 메모를 바꾼 뒤의 전체 내용(빈 문자열이면 메모를 지운다). 보낸 사람만 바꿀 수 있다."""

    memo: str = Field(max_length=2000)


class RecipientOut(BaseModel):
    user_id: str
    status: Literal["waiting", "accepted", "declined"]


class RequestOut(BaseModel):
    id: str
    from_id: str
    title: str
    start_date: date
    start_time: time | None
    end_time: time | None
    place: str
    memo: str
    created_at: datetime
    canceled: bool
    recipients: list[RecipientOut]
    my_event_id: str | None  # 내가 수락해서 만든 지워지지 않은 일정
    edited_at: datetime | None = None  # 받는 사람을 바꾼 마지막 시각
