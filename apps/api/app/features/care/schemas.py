from datetime import date as _date
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RecordPut(BaseModel):
    subject: str = Field(min_length=1, max_length=40)
    kind: Literal["condition", "meal", "medication", "walk"]
    value: str = Field(min_length=1, max_length=40)
    note: str = ""
    date: _date | None = None  # 비우면 오늘(한국 시간)


class RecordOut(BaseModel):
    id: str
    subject: str
    kind: str
    value: str
    note: str
    date: str
    created_by: str


class PutResult(BaseModel):
    record: RecordOut
    replaced: bool  # 같은 날 같은 종류의 기록을 덮어썼는지


class TodaySummary(BaseModel):
    date: str
    records: list[RecordOut]
    missing: list[str]  # 오늘 아직 기록이 없는 종류. "기록이 없다"는 "문제가 있다"는 뜻이 아니다.


# ---- 데일리 체크 ----

Mode = Literal["yesno", "number", "condition"]
Condition = Literal["good", "normal", "bad"]
MealType = Literal["breakfast", "lunch", "dinner"]


class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    mode: Mode
    unit: str = Field(default="", max_length=8)
    target: int | None = Field(default=None, ge=1, le=100000)  # 수치 항목만
    scheduled_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    meal_type: MealType | None = None  # 예/아니오 항목만. 식단 추천이 쓴다.


class EntryPut(BaseModel):
    date: _date | None = None  # 비우면 오늘(한국 시간)
    done: bool | None = None
    number: int | None = Field(default=None, ge=0, le=100000)
    condition: Condition | None = None
    skipped: bool = False  # true 면 값 없이 '건너뛰기'로 기록한다


class EntryOut(BaseModel):
    done: bool | None
    number: int | None
    condition: str | None
    recorded_by: str
    recorded_at: datetime
    skipped: bool = False
    late: bool = False  # 예정 시각 + 60분이 지난 뒤에 기록한 것(소급 입력)


class ItemOut(BaseModel):
    id: str
    name: str
    mode: str
    unit: str
    target: int | None
    scheduled_time: str
    meal_type: str | None
    entry: EntryOut | None = None
    completed: bool = False
    missing: bool = False  # 예정 시각 + 60분이 지나도 완료되지 않음 (서버가 계산)
    skipped: bool = False
    # done 완료 / skipped 건너뜀 / missing 누락 / due 예정 시각이 지났지만 60분 안 / upcoming 아직 전
    status: Literal["done", "skipped", "missing", "due", "upcoming"] = "upcoming"
    minutes_until: int | None = None  # 예정 시각까지 남은 분(지났으면 음수). 오늘이 아니면 None


class MealStatus(BaseModel):
    meal: MealType
    label: str  # 아침/점심/저녁
    item_id: str
    scheduled_time: str
    status: Literal["done", "skipped", "missing", "due", "upcoming"]
    answer: Literal["yes", "no"] | None = None  # 기록한 답(예/아니오)


class DailyOut(BaseModel):
    date: str
    now: str  # 누락 계산에 쓴 현재 시각 (HH:MM, 한국 시간)
    items: list[ItemOut]
    missing_ids: list[str]
    meals: list[MealStatus] = []  # 아침·점심·저녁 한눈에 보기(끼니가 지정된 항목)
    upcoming_ids: list[str] = []  # 지금 해야 할 것(due) → 다가오는 순서(upcoming)
    cleanup_ids: list[
        str
    ] = []  # 시간이 지난 미기록·누락(소급 입력 또는 건너뛰기 대상), 예정 시각 순
    skipped_ids: list[str] = []
    done_ids: list[str] = []


class RecommendationOut(BaseModel):
    rule: str
    item_id: str | None
    text: str


class RecommendationList(BaseModel):
    date: str
    recommendations: list[RecommendationOut]


class MealOut(BaseModel):
    meal: str
    label: str
    item_id: str | None
    menu: str
    index: int
    next_index: int
    total: int


class MealList(BaseModel):
    date: str
    meals: list[MealOut]  # 아직 기록되지 않은 끼니만


# ---- 위치 공유 ----


class ConsentOut(BaseModel):
    consent: bool
    since: datetime | None = None  # 동의한 시각


class ConsentSet(BaseModel):
    consent: bool


class LocationPoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100000)
    recorded_at: datetime  # 기기에서 위치를 잰 시각(시간대 포함, 예: 2026-10-22T09:00:00Z)


class LocationBatch(BaseModel):
    points: list[LocationPoint] = Field(min_length=1, max_length=50)


class LocationSaved(BaseModel):
    saved: int
    skipped: int  # 너무 오래됐거나 미래 시각이라 버린 개수


class MemberLocation(BaseModel):
    user_id: str
    name: str
    is_me: bool
    sharing: bool  # 위치 공유에 동의했는지. false 면 좌표를 내려주지 않는다.
    lat: float | None = None
    lng: float | None = None
    accuracy_m: float | None = None
    recorded_at: datetime | None = None
    minutes_ago: int | None = None


class LocationsLatest(BaseModel):
    members: list[MemberLocation]
    retention_days: int
