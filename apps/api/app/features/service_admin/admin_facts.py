"""서비스 관리자 화면의 숫자를 관리자 챗봇 명단(shared/admin_facts)에 올린다.

화면이 쓰는 함수를 그대로 불러서 챗봇 숫자와 화면 숫자가 같다.
개수·비율만 담는다. 이름·이메일·사용자 id 가 든 rows, 가족 이름이 든 top_families 는 쓰지 않는다.
"""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.shared.admin_facts import MAX_RANGE_DAYS, DateRange, parse_range, register
from app.shared.config import settings

from . import service
from .analytics import analytics

AI_DEFAULT_DAYS = 14  # AI 기간 질문에서 끝 날짜만 줬을 때 보는 일수(화면의 최근 14일과 같다)


def _num(value: float | None, unit: str) -> str:
    """아직 계산할 수 없는 값(None)은 0 이 아니라 '아직 없음'으로 보낸다."""
    return "아직 없음" if value is None else f"{value}{unit}"


def _today(now: datetime) -> date:
    """한국 시간 오늘 날짜."""
    return (now + timedelta(hours=settings.ai_day_utc_offset_hours)).date()


def members(db: Session) -> list[str]:
    m = service.members(db)
    return [
        f"전체 회원: {m.total}명",
        f"이번 주 가입: {m.joined_this_week}명",
        f"최근 7일 활성 사용자: {m.active_7d}명",
        f"가족 없는 회원: {m.no_family}명",
        f"이메일 인증 회원: {m.email_verified}명",
    ]


def groups(db: Session) -> list[str]:
    g = service.groups(db)
    return [
        f"가족 그룹: {g.total}개",
        f"구성원이 1명뿐인 가족: {g.single_member}곳",
        f"승인 대기 참가 요청: {g.pending_total}건",
        f"AI 를 켠 가족: {g.ai_enabled}곳",
    ]


def support(db: Session) -> list[str]:
    s = service.support(db)
    return [
        f"문의·신고: 새 문의 {s.new}건, 처리 중 {s.working}건, 답변 완료 {s.done}건, 신고 {s.reports}건"
    ]


def _day_start_utc(day: date) -> datetime:
    """한국 시간 그날 0시를 UTC 로(화면의 하루 경계 day_start 와 같다)."""
    return datetime.combine(day, time(), UTC) - timedelta(hours=settings.ai_day_utc_offset_hours)


def _days(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def ai(db: Session, start: str | None = None, end: str | None = None) -> list[str]:
    """날짜를 비우면 오늘·7일·30일 합계와 최근 14일. 기간을 주면 그 기간의 날짜별 값과 합계."""
    now = datetime.now(UTC)
    today = _today(now)
    if start is None and end is None:
        a = service.ai_usage(db, now)
        count = len(a.daily)
        return [
            f"AI 요청: 오늘 {a.today}회, 최근 7일 {a.week}회, 최근 30일 {a.month}회",
            *(
                f"일별 AI 요청 {today - timedelta(days=count - 1 - i)}: {a.daily[i]}회"
                for i in range(count)
            ),
        ]
    picked = parse_range(start, end, today, AI_DEFAULT_DAYS)
    if isinstance(picked, str):
        return [picked]
    days = _days(*picked)
    counts = service.ai_daily(db, _day_start_utc(days[0]), len(days))
    return [
        f"AI 요청 {days[0]} ~ {days[-1]} 합계: {sum(counts)}회",
        *(f"일별 AI 요청 {d}: {n}회" for d, n in zip(days, counts, strict=True)),
    ]


def daily_members(db: Session, start: str | None = None, end: str | None = None) -> list[str]:
    """회원 카드의 일별 그래프와 같은 값(한국 시간 날짜, 오래된 날 → 최근).
    날짜를 비우면 화면과 같은 최근 30일, 기간을 주면 그 기간과 기간 가입 합계."""
    now = datetime.now(UTC)
    today = _today(now)
    picked = parse_range(start, end, today, service.MEMBER_DAYS)
    if isinstance(picked, str):
        return [picked]
    days = _days(*picked)
    m = service.member_daily(db, now, first=_day_start_utc(days[0]), days=len(days))
    lines = [
        f"일별 회원 {d}: 가입 {m['joined'][i]}명, "
        f"그날 끝 전체 회원 {m['total'][i]}명, 활성 사용자 {m['active'][i]}명"
        for i, d in enumerate(days)
    ]
    if start is not None or end is not None:
        lines.insert(0, f"회원 {days[0]} ~ {days[-1]} 가입 합계: {sum(m['joined'])}명")
    return lines


def data_analysis(db: Session) -> list[str]:
    """데이터 분석 탭과 같은 계산."""
    a = analytics(db)
    lines = [
        f"재방문 코호트 {c.week_start} 주: 가입 {c.size}명, 1주 뒤 {_num(c.w1, '%')}, "
        f"2주 뒤 {_num(c.w2, '%')}, 4주 뒤 {_num(c.w4, '%')}"
        for c in a.retention
    ]
    lines += [
        f"가입 퍼널 {s.label}: {s.users}명({_num(s.share, '%')}), "
        f"가입부터 걸린 시간 중앙값 {_num(s.median_hours, '시간')}"
        for s in a.funnel
    ]
    lines += [
        f"가족 인원 {f.label}: {f.families}곳, 최근 7일 활동 가족 {_num(f.active_share, '%')}, "
        f"가족당 최근 7일 사용 {_num(f.avg_actions, '회')}"
        for f in a.families.by_size
    ]
    lines.append(
        f"두 번째 가족이 들어오기까지 중앙값: {_num(a.families.days_to_second_member, '일')}"
    )
    lines += [
        f"기능 사용 지도(최근 30일) {f.label}: {f.families}가족({_num(f.share, '%')})"
        for f in a.features
    ]
    x = a.ai
    lines.append(
        f"AI 품질·비용(최근 30일): 요청 {x.requests}회, 활동 사용자 {x.active_users}명, "
        f"1인당 {_num(x.per_active_user, '회')}, 오류율 {_num(x.error_rate, '%')}, "
        f"캐시 적중률 {_num(x.cache_hit_rate, '%')}, 한도 거절률 {_num(x.limit_rate, '%')}"
    )
    s = a.support
    lines.append(
        f"고객 응대: 문의 {s.inquiries}건, 신고 {s.reports}건, 답변 {s.answered}건, "
        f"평균 답변 시간 {_num(s.avg_hours, '시간')}"
    )
    return lines


register(
    "members",
    "전체 회원, 최근 7일 가입, 최근 7일 활성 사용자, 가족 없는 회원, 이메일 인증 회원 수.",
    members,
    order=10,
    label="회원 수 확인",
)
register(
    "members_daily",
    "날짜별 가입자, 그날 끝 전체 회원, 활성 사용자. 특정 날짜·기간의 값이나 사용자 증감을 볼 때 씁니다. "
    f"start·end(YYYY-MM-DD, 한국 시간)를 주면 그 기간(최대 {MAX_RANGE_DAYS}일)과 기간 가입 합계를, "
    "비우면 최근 30일을 줍니다.",
    daily_members,
    order=15,
    label="날짜별 회원 확인",
    params=DateRange,
)
register(
    "groups",
    "가족 그룹 수, 1명뿐인 가족, 승인 대기 참가 요청, AI 를 켠 가족 수.",
    groups,
    order=20,
    label="가족 그룹 확인",
)
register(
    "support",
    "문의·신고의 새 문의, 처리 중, 답변 완료, 신고 건수.",
    support,
    order=30,
    label="문의·신고 확인",
)
register(
    "ai_usage",
    "AI 요청 수. 사용량 변화를 비교할 때 씁니다. 비우면 오늘·최근 7일·최근 30일 합계와 최근 14일 날짜별 값을, "
    f"start·end(YYYY-MM-DD, 한국 시간)를 주면 그 기간(최대 {MAX_RANGE_DAYS}일)의 날짜별 값과 합계를 줍니다.",
    ai,
    order=40,
    label="AI 사용량 확인",
    params=DateRange,
)
register(
    "data_analysis",
    "데이터 분석 탭의 값: 가입 주별 재방문 코호트(최근 8주), 가입 퍼널, 가족 인원별 활동, "
    "기능 사용 지도, AI 품질(오류율·캐시·한도 거절), 고객 응대.",
    data_analysis,
    order=90,
    label="데이터 분석 확인",
)
