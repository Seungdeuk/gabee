from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.features.family_group.models import User

from . import repository
from .schemas import (
    AdminMeOut,
    FeatureRow,
    FeaturesOut,
    GroupRow,
    GroupSize,
    GroupsOut,
    MemberRow,
    MembersOut,
    TesterRow,
    TestersOut,
)

WEEK = timedelta(days=7)

# (key, 화면 이름, 표, 시각 칸). 개수만 센다.
FEATURES = (
    ("schedule", "일정", "events", "created_at"),
    ("chat", "소통", "messages", "created_at"),
    ("care", "돌봄", "care_entries", "recorded_at"),
    ("billing", "정산", "expenses", "created_at"),
)


def me_out(user: User) -> AdminMeOut:
    return AdminMeOut(id=user.id, name=user.name, login_id=user.login_id)


def members(db: Session, now: datetime | None = None) -> MembersOut:
    now = now or datetime.now(UTC)
    return MembersOut(
        total=repository.count_users(db),
        joined_this_week=repository.count_users(db, since=now - WEEK),
        rows=[
            MemberRow(
                id=r["id"],
                name=r["name"],
                login_id=r["login_id"],
                joined_at=r["created_at"],
                has_family=bool(r["has_family"]),
                last_login_at=r["last_login_at"],
            )
            for r in repository.recent_members(db)
        ],
    )


def groups(db: Session) -> GroupsOut:
    total, rows = repository.groups_with_counts(db)
    sizes = Counter(r["members"] for r in rows)
    return GroupsOut(
        total=total,
        rows=[GroupRow(**r) for r in rows[: repository.LIST_LIMIT]],
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


def testers(db: Session) -> TestersOut:
    return TestersOut(rows=[TesterRow(**r) for r in repository.testers(db)])
