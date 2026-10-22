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


class EntryOut(BaseModel):
    done: bool | None
    number: int | None
    condition: str | None
    recorded_by: str
    recorded_at: datetime


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


class DailyOut(BaseModel):
    date: str
    now: str  # 누락 계산에 쓴 현재 시각 (HH:MM, 한국 시간)
    items: list[ItemOut]
    missing_ids: list[str]


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


class LocationOut(BaseModel):
    is_example: bool
    place: str
    lat: float
    lng: float
    notice: str
