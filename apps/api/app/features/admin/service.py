from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.ai_guard import day_start

from . import repository
from .schemas import (
    AdminAiFamilyRow,
    AdminAiFeatureRow,
    AdminAiLimitedRow,
    AdminAiUsageOut,
    AdminAiUserRow,
    AdminMeOut,
    FeatureRow,
    FeaturesOut,
    GroupRow,
    GroupSize,
    GroupsOut,
    MemberRow,
    MembersOut,
)

WEEK = timedelta(days=7)

# (key, 화면 이름, 표, 시각 칸). 개수만 센다.
FEATURES = (
    ("schedule", "일정", "events", "created_at"),
    ("chat", "소통", "messages", "created_at"),
    ("billing", "정산", "expenses", "created_at"),
)


DAY = timedelta(days=1)

# ai_usage_logs.feature → 화면 이름. 목록에 없는 값은 key 를 그대로 보여 준다
AI_FEATURE_NAMES = {
    "assistant_chat": "AI 비서 채팅",
    "knowledge_ask": "기록 질문",
    "schedule_chat": "일정 에이전트",
    "schedule_card": "일정 카드 만들기",
    "billing_agent": "정산 에이전트",
    "family_chat_agent": "가족 채팅 에이전트",
    "analysis": "가족 채팅 분석",
    "reply": "답장 추천",
    "topics": "대화 주제 추천",
    "doc_summary": "문서 요약(이전 기능)",
    "doc_answer": "문서 질문(이전 기능)",
}


def me_out(user: User) -> AdminMeOut:
    return AdminMeOut(id=user.id, name=user.name, login_id=user.login_id)


def members(db: Session, now: datetime | None = None) -> MembersOut:
    now = now or datetime.now(UTC)
    active_7d, no_family, email_verified = repository.member_totals(db, now - WEEK)
    return MembersOut(
        total=repository.count_users(db),
        joined_this_week=repository.count_users(db, since=now - WEEK),
        active_7d=active_7d,
        no_family=no_family,
        email_verified=email_verified,
        rows=[
            MemberRow(
                id=r["id"],
                name=r["name"],
                login_id=r["login_id"],
                joined_at=r["created_at"],
                has_family=bool(r["has_family"]),
                email_verified=bool(r["email_verified"]),
                last_login_at=r["last_login_at"],
            )
            for r in repository.recent_members(db)
        ],
    )


def groups(db: Session) -> GroupsOut:
    total, rows = repository.groups_with_counts(db)
    sizes = Counter(r["members"] for r in rows)
    pending_total, oldest_pending_at, ai_enabled = repository.join_and_ai_totals(db)
    return GroupsOut(
        total=total,
        single_member=sizes.get(1, 0),
        pending_total=pending_total,
        oldest_pending_at=oldest_pending_at,
        ai_enabled=ai_enabled,
        rows=[
            GroupRow(**{**r, "ai_enabled": bool(r["ai_enabled"])})
            for r in rows[: repository.LIST_LIMIT]
        ],
        sizes=[GroupSize(members=k, groups=v) for k, v in sorted(sizes.items())],
    )


def features(db: Session, now: datetime | None = None) -> FeaturesOut:
    now = now or datetime.now(UTC)
    rows = []
    for key, name, table, col in FEATURES:
        uses, families = repository.feature_usage(db, table, col, now - WEEK, now)
        prev_uses, _ = repository.feature_usage(db, table, col, now - 2 * WEEK, now - WEEK)
        rows.append(
            FeatureRow(key=key, name=name, families=families, uses=uses, prev_uses=prev_uses)
        )
    return FeaturesOut(families_total=repository.count_groups(db), rows=rows)


def _limited(hits: list[dict]) -> list[AdminAiLimitedRow]:
    """한도에 막힌 기록(최근순)을 사람별로 묶는다. 날짜는 한국 시간 자정 경계로 센다."""
    by_user: dict[str, dict] = {}
    for h in hits:
        at = h["created_at"]
        if at.tzinfo is None:  # SQLite 는 시간대를 떼고 돌려준다
            at = at.replace(tzinfo=UTC)
        u = by_user.setdefault(
            h["user_id"],
            {"name": h["name"], "group_name": h["group_name"], "last_at": at, "days": set()},
        )
        u["days"].add(day_start(at))
    rows = [
        AdminAiLimitedRow(
            user_id=uid,
            name=u["name"],
            group_name=u["group_name"],
            days=len(u["days"]),
            last_at=u["last_at"],
        )
        for uid, u in by_user.items()
    ]
    rows.sort(key=lambda r: r.last_at, reverse=True)
    return rows[: repository.LIST_LIMIT]


def ai_usage(db: Session, now: datetime | None = None) -> AdminAiUsageOut:
    now = now or datetime.now(UTC)
    today = day_start(now)
    month_start = today - 29 * DAY
    return AdminAiUsageOut(
        today=repository.count_ai_requests(db, today),
        week=repository.count_ai_requests(db, today - 6 * DAY),
        month=repository.count_ai_requests(db, month_start),
        daily=[
            repository.count_ai_requests(db, today - i * DAY, today - (i - 1) * DAY)
            for i in range(13, -1, -1)
        ],
        rows=[
            AdminAiFeatureRow(
                key=key,
                name=AI_FEATURE_NAMES.get(key, key),
                calls=direct + via,
                direct=direct,
                via_assistant=via,
            )
            for key, direct, via in repository.ai_requests_by_feature(db, month_start)
        ],
        families=[AdminAiFamilyRow(**r) for r in repository.ai_requests_by_group(db, month_start)],
        users=[AdminAiUserRow(**r) for r in repository.ai_requests_by_user(db, month_start)],
        limited=_limited(repository.ai_limit_hits(db, month_start)),
    )
