import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

NewsStatus = Literal["ready", "pending", "failed", "empty", "not_generated", "too_early"]


class NewsItemOut(BaseModel):
    text: str
    source_ids: list[str]


class NewsSourceOut(BaseModel):
    id: str
    kind: Literal["event", "todo", "document"]
    ref: str
    label: str
    date: dt.date | None = None


class NewsOut(BaseModel):
    """한 구성원의 한 주 뉴스. 저장본이 없으면 status 만 있고 나머지는 비어 있다(읽기는 아무것도 만들지 않는다)."""

    status: NewsStatus
    week_start: dt.date
    week_end: dt.date
    title: str | None = None
    items: list[NewsItemOut] = Field(default_factory=list)
    sources: list[NewsSourceOut] = Field(default_factory=list)
    generated_at: dt.datetime | None = None
    ai_generated: bool = False
    model: str | None = None
