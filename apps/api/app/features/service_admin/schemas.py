from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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
    email_verified: bool  # 이메일 주소는 돌려주지 않고 인증 여부만
    last_login_at: datetime | None  # 마지막으로 로그인 토큰을 받은 시각


class MembersOut(BaseModel):
    total: int
    joined_this_week: int  # 최근 7일
    active_7d: int  # 최근 7일에 로그인·자동 갱신으로 토큰을 받은 사람 수
    no_family: int  # 어느 가족에도 속하지 않은 사람 수
    email_verified: int  # 이메일 인증을 마친 사람 수
    rows: list[MemberRow]  # 최근 가입순, 최대 200명


class GroupRow(BaseModel):
    id: str
    name: str
    owner_name: str | None
    members: int
    pending: int  # 승인 대기 중인 가입 요청 수
    ai_enabled: bool
    created_at: datetime


class GroupSize(BaseModel):
    members: int
    groups: int


class GroupsOut(BaseModel):
    total: int
    single_member: int  # 구성원이 1명뿐인 그룹 수
    pending_total: int  # 승인 대기 가입 요청 전체
    oldest_pending_at: datetime | None  # 가장 오래된 대기 요청 시각
    ai_enabled: int  # AI 사용을 켠 그룹 수
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


class AdminAiFeatureRow(BaseModel):
    key: str
    name: str
    calls: int  # 최근 30일 합계 = direct + via_assistant
    direct: int  # 사용자가 이 기능을 직접 쓴 수
    via_assistant: (
        int  # 메인 AI 비서가 안에서 이 에이전트를 부른 수(사용자 요청 수에는 넣지 않는다)
    )


class AdminAiFamilyRow(BaseModel):
    group_id: str
    name: str | None
    requests: int  # 최근 30일 요청 수
    errors: int


class AdminAiUserRow(BaseModel):
    user_id: str
    name: str | None
    login_id: str | None
    requests: int  # 최근 30일 요청 수
    errors: int


class AdminAiLimitedRow(BaseModel):
    user_id: str
    name: str | None
    group_name: str | None  # 가장 최근에 막힌 기록의 가족
    days: int  # 최근 30일 중 한도에 막힌 날 수(한국 시간 기준)
    last_at: datetime


class AdminAiUsageOut(BaseModel):
    # 요청 수: 사용자가 AI 기능을 한 번 쓰면 1(캐시 적중·오류 포함, nested·rejected 표식 제외). 날짜 경계는 한국 시간 자정
    today: int
    week: int  # 오늘 포함 최근 7일
    month: int  # 오늘 포함 최근 30일
    daily: list[int]  # 최근 14일, 오래된 날 → 오늘
    rows: list[AdminAiFeatureRow]  # 최근 30일, 많은 순
    families: list[AdminAiFamilyRow]  # 최근 30일, 많은 순, 최대 200
    users: list[AdminAiUserRow]  # 최근 30일, 많은 순, 최대 200
    limited: list[AdminAiLimitedRow]  # 최근 30일 일일 한도에 막힌 사람, 최근순, 최대 200


class AdminTicketRow(BaseModel):
    id: str
    kind: Literal["inquiry", "report"]
    title: str
    body: str  # 사용자가 직접 쓴 글. 가족 채팅 내용은 담기지 않는다
    status: Literal["new", "working", "done"]
    answer: str | None
    answered_at: datetime | None
    created_at: datetime
    user_name: str | None
    login_id: str | None
    group_name: str | None


class AdminTicketsOut(BaseModel):
    new: int
    working: int
    done: int
    reports: int  # 신고 건수(문의와 따로)
    rows: list[AdminTicketRow]  # 최근순, 최대 200


class AdminTicketUpdate(BaseModel):
    status: Literal["new", "working", "done"] | None = None
    answer: str | None = Field(default=None, min_length=1, max_length=2000)


class AdminNoticeIn(BaseModel):
    """공지 쓰기·고치기. 종류는 update(업데이트)/info(안내)/maintenance(점검)."""

    category: Literal["update", "info", "maintenance"]
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=5000)


class AdminNoticeRow(BaseModel):
    id: str
    category: Literal["update", "info", "maintenance"]
    title: str
    body: str
    created_at: datetime
    updated_at: datetime


class AdminNoticesOut(BaseModel):
    rows: list[AdminNoticeRow]  # 최근순, 최대 200
