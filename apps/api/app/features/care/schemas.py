from datetime import datetime

from pydantic import BaseModel, Field

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
