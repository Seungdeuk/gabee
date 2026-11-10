"""서비스 관리자 '데이터 분석' 탭의 계산. 표에서 id·시각·개수만 읽어 파이썬으로 센다(채팅·일정·가계 내용은 읽지 않는다).

- 활동 기준: 로그인·자동 갱신으로 토큰을 받은 시각(refresh_tokens.issued_at). 지워진 토큰은 기록이 없다.
- 날짜·요일·시간 경계: 한국 시간(settings.ai_day_utc_offset_hours, 기본 +9).
- 사람이 적을 때는 비율이 크게 흔들린다(화면에 안내한다)."""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from statistics import median

from sqlalchemy.orm import Session

from app.shared.config import settings

from . import repository
from .schemas import (
    AnalyticsAi,
    AnalyticsAiFamily,
    AnalyticsCohort,
    AnalyticsFamilies,
    AnalyticsFamilySize,
    AnalyticsFeature,
    AnalyticsFunnelStep,
    AnalyticsOut,
    AnalyticsSupport,
)

DAY = timedelta(days=1)
WEEK = timedelta(days=7)
COHORT_WEEKS = 8
RETENTION_WEEKS = (1, 2, 4)
WINDOW = 30 * DAY  # 가족·기능·AI·시간대 분석 기간
SIZE_LABELS = ("1명", "2명", "3명", "4명", "5명 이상")
FEATURE_NAMES = (("schedule", "일정"), ("chat", "채팅"), ("billing", "정산"), ("ai", "AI"))


def _aware(at: datetime | None) -> datetime | None:
    """SQLite 는 시간대 없는 값을 돌려준다(UTC 로 저장했다)."""
    return at.replace(tzinfo=UTC) if at is not None and at.tzinfo is None else at


def _local(at: datetime) -> datetime:
    return at + timedelta(hours=settings.ai_day_utc_offset_hours)


def _week_start(at: datetime) -> datetime:
    """at 이 든 한국 시간 주(월요일 0시)의 시작을 UTC 로."""
    offset = timedelta(hours=settings.ai_day_utc_offset_hours)
    local = _local(at)
    monday = (local - timedelta(days=local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday - offset


def _pct(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


def _hours(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600


def retention(users: dict[str, datetime], tokens: list[tuple[str, datetime]], now: datetime):
    """가입 주별로 묶고, 가입 뒤 k주째(가입 시각 기준 7일씩)에 토큰을 받은 사람 비율. 아직 지나지 않은 주는 None."""
    by_user: dict[str, list[datetime]] = defaultdict(list)
    for uid, at in tokens:
        by_user[uid].append(at)
    this_week = _week_start(now)
    rows = []
    for i in range(COHORT_WEEKS - 1, -1, -1):
        start = this_week - i * WEEK
        cohort = [uid for uid, at in users.items() if start <= at < start + WEEK]
        rates = {}
        for k in RETENTION_WEEKS:
            if (
                start + WEEK + (k + 1) * WEEK > now
            ):  # 이 주에 가입한 모두가 k주째를 다 지나지 않았다
                rates[k] = None
                continue
            back = sum(
                1
                for uid in cohort
                if any(
                    users[uid] + k * WEEK <= at < users[uid] + (k + 1) * WEEK for at in by_user[uid]
                )
            )
            rates[k] = _pct(back, len(cohort))
        rows.append(
            AnalyticsCohort(
                week_start=_local(start).date(),
                size=len(cohort),
                w1=rates[1],
                w2=rates[2],
                w4=rates[4],
            )
        )
    return rows


def funnel(users: dict[str, datetime], firsts: dict[str, dict[str, datetime]]):
    """가입 → 가족 연결 → 첫 일정·채팅 → 첫 AI. 각 단계는 앞 단계를 모두 지난 사람만 센다.
    걸린 시간은 가입부터 그 단계까지의 중앙값(시간)."""
    steps = (
        ("signup", "가입"),
        ("family", "가족 연결"),
        ("first_use", "첫 일정·채팅"),
        ("ai", "첫 AI 사용"),
    )
    reached = set(users)
    out = []
    for key, label in steps:
        if key != "signup":
            reached = {uid for uid in reached if uid in firsts[key]}
        waits = (
            [max(0.0, _hours(users[uid], firsts[key][uid])) for uid in reached]
            if key != "signup"
            else []
        )
        out.append(
            AnalyticsFunnelStep(
                key=key,
                label=label,
                users=len(reached),
                share=_pct(len(reached), len(users)),
                median_hours=round(median(waits), 1) if waits else None,
            )
        )
    return out


def analytics(db: Session, now: datetime | None = None) -> AnalyticsOut:
    now = now or datetime.now(UTC)
    since = now - WINDOW
    raw = repository.analytics_rows(db, now - (COHORT_WEEKS + 6) * WEEK, since)

    users = {uid: _aware(at) for uid, at in raw["users"]}
    tokens = [(uid, _aware(at)) for uid, at in raw["tokens"]]
    groups = {gid: (name, _aware(at)) for gid, name, at in raw["groups"]}
    members: dict[str, list[datetime]] = defaultdict(list)
    first_family: dict[str, datetime] = {}
    for gid, uid, at in raw["members"]:
        at = _aware(at)
        members[gid].append(at)
        first_family[uid] = min(at, first_family.get(uid, at))
    first_use: dict[str, datetime] = {}
    for uid, at in raw["first_event"] + raw["first_message"]:
        if uid is not None and at is not None:
            at = _aware(at)
            first_use[uid] = min(at, first_use.get(uid, at))
    first_ai = {uid: _aware(at) for uid, at in raw["first_ai"] if uid is not None}

    # 가족별 최근 활동(30일): 일정·채팅·정산·AI 요청 시각
    actions: dict[str, dict[str, list[datetime]]] = {k: defaultdict(list) for k, _ in FEATURE_NAMES}
    for key in ("schedule", "chat", "billing"):
        for gid, at in raw[key]:
            actions[key][gid].append(_aware(at))
    ai_logs = [
        (gid, uid, status, bool(cache), (i or 0) + (o or 0), _aware(at))
        for gid, uid, status, cache, i, o, at in raw["ai"]
    ]
    requests = [r for r in ai_logs if r[2] not in repository.MARKER_STATUSES]
    for gid, *_rest, at in requests:
        if gid:
            actions["ai"][gid].append(at)

    # 가족 인원별
    week_ago = now - WEEK
    sizes: dict[str, list[str]] = defaultdict(list)
    for gid in groups:
        n = len(members.get(gid, []))
        sizes[SIZE_LABELS[min(max(n, 1), 5) - 1]].append(gid)
    by_size = []
    for label in SIZE_LABELS:
        gids = sizes.get(label, [])
        weekly = [
            sum(sum(1 for a in actions[k].get(g, []) if a >= week_ago) for k, _ in FEATURE_NAMES)
            for g in gids
        ]
        by_size.append(
            AnalyticsFamilySize(
                label=label,
                families=len(gids),
                active_share=_pct(sum(1 for w in weekly if w), len(gids)),
                avg_actions=round(sum(weekly) / len(gids), 1) if gids else None,
            )
        )
    to_two = [
        (sorted(joined)[1] - groups[gid][1]).total_seconds() / 86400
        for gid, joined in members.items()
        if len(joined) >= 2 and gid in groups
    ]
    families = AnalyticsFamilies(
        by_size=by_size,
        solo_families=len(sizes.get(SIZE_LABELS[0], [])),
        days_to_second_member=round(median(to_two), 1) if to_two else None,
    )

    total_groups = len(groups)
    features = [
        AnalyticsFeature(
            key=key,
            label=label,
            families=len(actions[key]),
            share=_pct(len(actions[key]), total_groups),
        )
        for key, label in FEATURE_NAMES
    ]

    # AI 품질·비용(30일)
    active_users = {uid for uid, at in tokens if at >= since}
    rejected = sum(1 for r in ai_logs if r[2] == "rejected")
    tokens_by_group: Counter = Counter()
    req_by_group: Counter = Counter()
    for gid, _uid, _status, _cache, used, _at in requests:
        tokens_by_group[gid] += used
        req_by_group[gid] += 1
    ai = AnalyticsAi(
        requests=len(requests),
        active_users=len(active_users),
        per_active_user=round(len(requests) / len(active_users), 1) if active_users else None,
        error_rate=_pct(sum(1 for r in requests if r[2] == "error"), len(requests)),
        cache_hit_rate=_pct(sum(1 for r in requests if r[3]), len(requests)),
        limit_rate=_pct(rejected, len(requests) + rejected),
        top_families=[
            AnalyticsAiFamily(
                name=groups.get(gid, ("(가족 없음)",))[0] if gid else "(가족 없음)",
                requests=req_by_group[gid],
                tokens=used,
            )
            for gid, used in tokens_by_group.most_common(5)
        ],
    )

    # 요일(월~일) × 시간(0~23) 활동: 토큰을 받은 때 + AI 요청
    heat = [[0] * 24 for _ in range(7)]
    for at in [a for _u, a in tokens if a >= since] + [r[5] for r in requests]:
        local = _local(at)
        heat[local.weekday()][local.hour] += 1

    # 고객 응대
    tickets = [(kind, _aware(c), _aware(a)) for kind, c, a in raw["support"]]
    waits = [_hours(c, a) for _k, c, a in tickets if a is not None]
    this_week = _week_start(now)
    weekly = [
        sum(1 for _k, c, _a in tickets if this_week - i * WEEK <= c < this_week - (i - 1) * WEEK)
        for i in range(COHORT_WEEKS - 1, -1, -1)
    ]
    support = AnalyticsSupport(
        inquiries=sum(1 for k, *_ in tickets if k == "inquiry"),
        reports=sum(1 for k, *_ in tickets if k == "report"),
        answered=len(waits),
        avg_hours=round(sum(waits) / len(waits), 1) if waits else None,
        max_hours=round(max(waits), 1) if waits else None,
        weekly=weekly,
        week_start=_local(this_week - (COHORT_WEEKS - 1) * WEEK).date(),
    )

    return AnalyticsOut(
        users=len(users),
        retention=retention(users, tokens, now),
        funnel=funnel(users, {"family": first_family, "first_use": first_use, "ai": first_ai}),
        families=families,
        features=features,
        total_families=total_groups,
        ai=ai,
        heatmap=heat,
        support=support,
    )
