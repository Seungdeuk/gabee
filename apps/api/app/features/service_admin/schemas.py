from datetime import date, datetime
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
    # 카드를 누르면 보이는 하루 그래프: 30개, 30일 전 → 오늘(한국 시간 자정 기준)
    daily_joined: list[int]  # 그날 가입
    daily_total: list[int]  # 그날 끝 기준 전체 가입자
    daily_active: list[int]  # 그날 로그인·자동 갱신으로 토큰을 받은 사람
    daily_no_family: list[int]  # 그날 끝 기준 가족 없는 회원
    daily_verified: list[int]  # 그날 끝 기준 이메일 인증
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


# ---------- 데이터 분석 탭 ----------
class AnalyticsCohort(BaseModel):
    week_start: date  # 가입 주의 월요일(한국 시간)
    size: int  # 그 주 가입자 수
    w1: float | None  # 가입 1주 뒤에 다시 쓴 비율(%). 아직 안 지났으면 None
    w2: float | None
    w4: float | None


class AnalyticsFunnelStep(BaseModel):
    key: str
    label: str
    users: int  # 이 단계까지 모두 지난 사람
    share: float | None  # 가입자 대비 %
    median_hours: float | None  # 가입부터 이 단계까지 걸린 시간 중앙값


class AnalyticsFamilySize(BaseModel):
    label: str  # 1명 ~ 5명 이상
    families: int
    active_share: float | None  # 최근 7일에 일정·채팅·정산·AI 중 하나라도 쓴 가족 %
    avg_actions: float | None  # 가족당 최근 7일 사용 수


class AnalyticsFamilies(BaseModel):
    by_size: list[AnalyticsFamilySize]
    solo_families: int  # 지금 1명뿐인 가족
    days_to_second_member: float | None  # 가족을 만든 뒤 두 번째 사람이 들어오기까지(중앙값, 일)


class AnalyticsFeature(BaseModel):
    key: str
    label: str
    families: int  # 최근 30일에 이 기능을 쓴 가족 수
    share: float | None  # 전체 가족 대비 %


class AnalyticsAiFamily(BaseModel):
    name: str
    requests: int
    tokens: int  # 입력 + 출력 토큰(비용의 기준)


class AnalyticsAi(BaseModel):
    requests: int  # 최근 30일 요청 수(표식 줄 제외)
    active_users: int  # 최근 30일 활동한 사람
    per_active_user: float | None
    error_rate: float | None  # %
    cache_hit_rate: float | None  # %
    limit_rate: float | None  # 한도·쿨다운으로 거절된 비율 %
    top_families: list[AnalyticsAiFamily]  # 토큰을 많이 쓴 가족 5곳


class AnalyticsSupport(BaseModel):
    inquiries: int
    reports: int
    answered: int
    avg_hours: float | None  # 문의부터 답변까지 평균 시간
    max_hours: float | None
    weekly: list[int]  # 주별 문의·신고 수(8주, 오래된 주 → 이번 주)
    week_start: date  # weekly 첫 주의 월요일


class AnalyticsSource(BaseModel):
    source: str  # utm_source 값(youtube, google-play …). 기록이 없는 가입자는 unknown
    signups: int  # 이 경로로 가입한 사람
    share: float | None  # 전체 가입자 대비 %
    family_rate: float | None  # 그중 가족에 들어간 사람 %


class AnalyticsUsageTab(BaseModel):
    tab: str  # chat, family-chat, schedule, care, my, other
    minutes: float  # 30일 동안 그 탭에 머문 분 합계
    share: float | None  # 전체 탭 시간 대비 %


class AnalyticsUsageDay(BaseModel):
    day: date
    users: int  # 그날 기록이 있는 사람
    avg_minutes: float | None  # 그날 1명당 평균 사용 분


class AnalyticsUsage(BaseModel):
    users: int  # 30일 동안 기록이 있는 사람
    avg_minutes_per_day: float | None  # 1명당 하루 평균 사용 분(기록이 있는 날 기준)
    avg_opens_per_day: float | None  # 1명당 하루 평균 실행 횟수
    by_tab: list[AnalyticsUsageTab]  # 많은 순
    daily: list[AnalyticsUsageDay]  # 30일, 오래된 날 → 오늘


class AnalyticsOut(BaseModel):
    users: int
    retention: list[AnalyticsCohort]  # 가입 주별(8주)
    funnel: list[AnalyticsFunnelStep]
    families: AnalyticsFamilies
    features: list[AnalyticsFeature]
    total_families: int
    ai: AnalyticsAi
    heatmap: list[list[int]]  # 7(월~일) × 24(시) 활동 수, 최근 30일
    support: AnalyticsSupport
    acquisition: list[AnalyticsSource]  # 유입 경로별 가입(많은 순, unknown 은 맨 끝)
    acquisition_ready: bool  # 유입 경로 표가 DB 에 있나(없으면 acquisition 은 빈 목록)
    usage: AnalyticsUsage | None  # 체류시간(최근 30일). 표가 없으면 None
    usage_ready: bool  # 체류시간 표가 DB 에 있나
