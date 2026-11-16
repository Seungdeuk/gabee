import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from .week import issue_of

NewsStatus = Literal["ready", "pending", "failed", "empty", "not_generated", "too_early"]


class NewsItemOut(BaseModel):
    """기사 하나. headline·role·category 는 기사형(v2) 뉴스에만 있고, 옛 저장본(v1)에서는 모두 null 이다.

    role: lead(메인 기사, 하나) | brief(단신). category 는 인용한 근거의 종류에서 서버가 정한 고정 이름이다."""

    text: str
    source_ids: list[str]
    headline: str | None = None
    role: Literal["lead", "brief"] | None = None
    category: str | None = None


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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def issue_year(self) -> int:
        """신문 호수의 연도(ISO). 모든 상태에서 week_start 로 계산한다(저장하지 않는다)."""
        return issue_of(self.week_start)[0]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def issue_no(self) -> int:
        """신문 호수(ISO 주 번호)."""
        return issue_of(self.week_start)[1]
