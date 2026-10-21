from datetime import date as _date
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
