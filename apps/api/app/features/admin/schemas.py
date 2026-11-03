from datetime import datetime

from pydantic import BaseModel


class AdminMeOut(BaseModel):
    id: str
    name: str
    login_id: str | None


class MemberRow(BaseModel):
    id: str
    name: str
    login_id: str | None
    joined_at: datetime
    has_family: bool
    last_login_at: datetime | None  # 마지막으로 로그인 토큰을 받은 시각


class MembersOut(BaseModel):
    total: int
    joined_this_week: int  # 최근 7일
    rows: list[MemberRow]  # 최근 가입순, 최대 200명


class GroupRow(BaseModel):
    id: str
    name: str
    owner_name: str | None
    members: int
    created_at: datetime


class GroupSize(BaseModel):
    members: int
    groups: int


class GroupsOut(BaseModel):
    total: int
    rows: list[GroupRow]  # 최근 생성순, 최대 200개
    sizes: list[GroupSize]  # 구성원 수별 그룹 수


class FeatureRow(BaseModel):
    key: str
    name: str
    families: int  # 최근 7일에 쓴 가족 수
    uses: int  # 최근 7일 사용 수
    prev_uses: int  # 그 전 7일 사용 수


class FeaturesOut(BaseModel):
    families_total: int
    rows: list[FeatureRow]


class TesterRow(BaseModel):
    id: str
    name: str
    login_id: str | None
    consent_at: datetime
    consent_version: str | None


class TestersOut(BaseModel):
    rows: list[TesterRow]
