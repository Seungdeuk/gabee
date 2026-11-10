"""데일리 체크 요청·응답 모양. 날짜는 요청에 받지 않는다(서버가 한국 시간 오늘을 정한다).

규칙 위반 중 입력 모양은 pydantic(422), 종류와 맞지 않는 필드·목표 없는 횟수 같은 업무 규칙은 서비스가 400 을 낸다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .constants import CHECK_COUNT_MAX, CHECK_GOAL_MAX, NOTE_MAX

_REPEAT_RE = r"^[01]{7}$"  # 월~일, 1 이 켜진 요일


def _strip_nonblank(v: str, label: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError(f"{label}이(가) 비었어요")
    return v


class CheckItemCreate(BaseModel):
    """내 습관 만들기. kind 1(한 번 체크)은 목표·단위를 보낼 수 없고, kind 2(횟수)는 목표가 필요하다(서비스가 검사)."""

    name: str = Field(min_length=1, max_length=60)
    kind: Literal[1, 2] = 1
    goal: int | None = Field(default=None, ge=1, le=CHECK_GOAL_MAX)
    unit: str = Field(default="", max_length=10)
    repeat_days: str = Field(default="1111111", pattern=_REPEAT_RE)
    shared: bool = True  # 가족에게 보이기
    notify: bool = False  # 알림(아직 저장만)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _strip_nonblank(v, "습관 이름")

    @field_validator("unit")
    @classmethod
    def _unit(cls, v: str) -> str:
        return v.strip()


class CheckItemUpdate(BaseModel):
    """바꿀 값만 보낸다. 보내지 않은 값은 그대로 둔다. goal 을 null 로 보내면 목표를 지운다(체크 습관일 때만 가능)."""

    name: str | None = Field(default=None, min_length=1, max_length=60)
    kind: Literal[1, 2] | None = None
    goal: int | None = Field(default=None, ge=1, le=CHECK_GOAL_MAX)
    unit: str | None = Field(default=None, max_length=10)
    repeat_days: str | None = Field(default=None, pattern=_REPEAT_RE)
    shared: bool | None = None
    notify: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return None if v is None else _strip_nonblank(v, "습관 이름")

    @field_validator("unit")
    @classmethod
    def _unit(cls, v: str | None) -> str | None:
        return None if v is None else v.strip()


class CheckItemOrder(BaseModel):
    """내 습관 전체의 새 순서(id 목록). 누락·중복·남의 습관은 400."""

    ids: list[str] = Field(max_length=200)


class CheckEntryBody(BaseModel):
    """그날 기록. 체크 습관은 done 만, 횟수 습관은 count(절대값)만 보낸다."""

    done: bool | None = None
    count: int | None = Field(default=None, ge=0, le=CHECK_COUNT_MAX)


class CheckNoteBody(BaseModel):
    """그날 메모. note 가 비어 있거나 null 이면 메모를 지운다. 100자를 넘으면 422."""

    note: str | None
    note_shared: bool = False  # 이 메모를 가족에게 보일지(습관이 가족에게 보일 때만 나간다)

    @field_validator("note")
    @classmethod
    def _note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if len(v) > NOTE_MAX:
            raise ValueError(f"메모는 {NOTE_MAX}자까지 쓸 수 있어요")
        return v.strip() or None


class CheckItemOut(BaseModel):
    id: str
    name: str
    kind: int
    goal: int | None
    unit: str
    repeat_days: str
    shared: bool
    notify: bool
    position: int
    # 요청한 날짜(없으면 오늘)의 기록. 줄이 없으면 미완료·0·메모 없음
    done: bool | None  # 체크 습관만 값이 있다
    count: int | None  # 횟수 습관만 값이 있다
    confirmed: bool
    confirmed_at: datetime | None
    note: str | None
    note_shared: bool
    applies: bool  # 그 날짜의 요일 패턴에 켜져 있는가(목록을 거르는 기준은 앱이 쓴다)
    updated_at: datetime  # 습관 정의가 마지막으로 실제로 바뀐 시각(순서·삭제는 아님)


class CheckMemberItemOut(BaseModel):
    """가족이 보는 습관 한 줄(오늘). 알림·순서·반복 요일은 싣지 않는다. 메모는 습관과 줄이 모두 공유일 때만 값이 있다."""

    id: str
    name: str
    kind: int
    goal: int | None
    unit: str
    done: bool | None
    count: int | None
    confirmed: bool
    confirmed_at: datetime | None
    note: str | None


class CheckMemberToday(BaseModel):
    user_id: str
    name: str
    items: list[CheckMemberItemOut]  # 가족에게 보이는 습관 중 오늘 요일에 해당하는 것만


class CheckMemberSummary(BaseModel):
    user_id: str
    name: str
    total: int  # 오늘 해당하는 가족에게 보이는 습관 수
    done: int  # 그중 오늘 완료 수


class CheckCheerCreate(BaseModel):
    to_user_id: str = Field(min_length=1, max_length=32)
    kind: Literal[1, 2, 3]  # 1 사랑해요 · 2 최고예요 · 3 잘하셨어요
    message: str = Field(min_length=1, max_length=100)
    chat_left: bool = False  # 가족 대화방에도 남길지(저장만, 아직 연동 없음)

    @field_validator("message")
    @classmethod
    def _message(cls, v: str) -> str:
        return _strip_nonblank(v, "한마디")


class CheckCheerOut(BaseModel):
    id: str
    from_user_id: str
    from_name: str
    to_user_id: str
    to_name: str
    kind: int
    message: str
    chat_left: bool
    sent_at: datetime
    thanked_at: datetime | None
    closed: bool  # 받은 사람이 카드를 닫았는가
    closed_at: datetime | None


class CheckSettingsIn(BaseModel):
    onboarded: bool


class CheckSettingsOut(BaseModel):
    onboarded: bool
