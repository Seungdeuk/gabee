from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ConsentIn(BaseModel):
    consent: bool


class BackgroundIn(BaseModel):
    """앱이 꺼져 있어도 위치를 모으는 것에 동의(true)하거나 끈다(false)."""

    enabled: bool


class PauseIn(BaseModel):
    """days 가 없거나 0 이면 일시정지를 푼다. 최대 14일. 오늘을 1일째로 세어 days 일째 날이 끝나는 자정(한국 시간)에 끝난다."""

    days: int | None = Field(default=None, ge=0, le=14)


class PointIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100000)
    recorded_at: datetime | None = None  # 없으면 서버가 받은 시각


class ZoneOut(BaseModel):
    center_lat: float
    center_lng: float
    radius_m: float
    sample_count: int
    computed_at: datetime


class MyLocationOut(BaseModel):
    enabled: bool  # 서버 스위치(LOCATION_ENABLED)
    consent: bool
    paused_until: datetime | None = None
    paused: bool = False
    background: bool = False  # 앱이 꺼져 있어도 위치를 모으는 것에 동의했는지
    zone: ZoneOut | None = None
    point_count: int = 0


class PointSaved(BaseModel):
    saved: bool
    reason: Literal["paused", "no_consent"] | None = None
    outside: bool = False  # 저장한 위치가 활동 구역 밖인지
    alerted: bool = False  # 이 요청으로 부모에게 알림을 보냈는지


class MemberLocation(BaseModel):
    user_id: str
    name: str
    is_me: bool
    sharing: bool  # 동의했고 일시정지 중이 아님
    paused: bool = False
    lat: float | None = None
    lng: float | None = None
    recorded_at: datetime | None = None
    outside: bool = False
    zone: ZoneOut | None = None


class FamilyLocations(BaseModel):
    members: list[MemberLocation]
    can_see_family: bool  # 부모(관리자)만 가족의 위치를 본다


class AskIn(BaseModel):
    """위치 기록 질문. history 는 앞선 대화(역할 user/assistant, 글)다."""

    question: str = Field(min_length=1, max_length=300)
    history: list[dict] | None = Field(default=None, max_length=10)


class AskOut(BaseModel):
    answer: str
    used_tool: bool  # 위치 기록을 찾아서 답했는지


class SimulateIn(BaseModel):
    """시연용: 지정한 사용자(기본은 나)의 현재 위치를 활동 구역에서 멀리 옮긴 것처럼 한 번 보낸다."""

    distance_m: float = Field(default=5000, ge=100, le=500000)


class SegmentOut(BaseModel):
    """하루 이동 기록의 한 구간. 좌표는 담지 않는다."""

    kind: Literal["stay", "move", "no_record", "anomaly"]
    start: datetime
    end: datetime
    place: str | None = None  # 이름을 붙인 곳의 이름(이동은 도착지). 이름 없는 곳은 비어 있다
    origin: str | None = None  # 이동의 출발지 이름
    candidate_id: str | None = None  # 자주 간 이름 없는 곳이면 이름 붙이기용 id


class TimelineOut(BaseModel):
    date: str
    user_id: str
    name: str
    sharing: bool  # 위치 공유에 동의한 사람인지
    can_name: bool  # 장소 이름은 본인만 붙인다
    segments: list[SegmentOut]


class PlaceOut(BaseModel):
    id: str
    name: str


class CandidateOut(BaseModel):
    id: str
    label: str  # "자주 가는 곳 1"
    visits: int
    last_seen: datetime


class PlacesOut(BaseModel):
    places: list[PlaceOut]
    candidates: list[CandidateOut]


class NamePlaceIn(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=20)
