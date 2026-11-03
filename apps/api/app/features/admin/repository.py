"""관리자 집계용 읽기 전용 조회. 다른 기능의 모델 파일을 import 하지 않고 공용 메타데이터의 표로 센다.
가족 데이터의 내용(채팅 글, 일정 제목, 금액 등)은 읽지 않고 개수와 시각만 쓴다."""

from datetime import datetime

from sqlalchemy import Table, func, select
from sqlalchemy.orm import Session

from app.shared.db import Base

LIST_LIMIT = 200


def _t(name: str) -> Table:
    return Base.metadata.tables[name]


def count_users(db: Session, since: datetime | None = None) -> int:
    users = _t("users")
    q = select(func.count()).select_from(users)
    if since is not None:
        q = q.where(users.c.created_at >= since)
    return db.scalar(q) or 0


def recent_members(db: Session) -> list[dict]:
    users, members, tokens = _t("users"), _t("group_members"), _t("refresh_tokens")
    family = select(members.c.user_id).distinct().subquery()
    last_login = (
        select(tokens.c.user_id, func.max(tokens.c.issued_at).label("last_login_at"))
        .group_by(tokens.c.user_id)
        .subquery()
    )
    q = (
        select(
            users.c.id,
            users.c.name,
            users.c.login_id,
            users.c.created_at,
            family.c.user_id.is_not(None).label("has_family"),
            last_login.c.last_login_at,
        )
        .outerjoin(family, family.c.user_id == users.c.id)
        .outerjoin(last_login, last_login.c.user_id == users.c.id)
        .order_by(users.c.created_at.desc())
        .limit(LIST_LIMIT)
    )
    return [dict(r._mapping) for r in db.execute(q)]


def groups_with_counts(db: Session) -> tuple[int, list[dict]]:
    groups, members, users = _t("groups"), _t("group_members"), _t("users")
    size = (
        select(members.c.group_id, func.count().label("members"))
        .group_by(members.c.group_id)
        .subquery()
    )
    q = (
        select(
            groups.c.id,
            groups.c.name,
            users.c.name.label("owner_name"),
            func.coalesce(size.c.members, 0).label("members"),
            groups.c.created_at,
        )
        .outerjoin(size, size.c.group_id == groups.c.id)
        .outerjoin(users, users.c.id == groups.c.owner_id)
        .order_by(groups.c.created_at.desc())
    )
    rows = [dict(r._mapping) for r in db.execute(q)]
    return len(rows), rows


def feature_usage(
    db: Session, table: str, time_col: str, since: datetime, until: datetime
) -> tuple[int, int]:
    """[since, until) 동안의 (사용 수, 쓴 가족 수)."""
    t = _t(table)
    col = t.c[time_col]
    q = select(func.count(), func.count(t.c.group_id.distinct())).where(col >= since, col < until)
    uses, families = db.execute(q).one()
    return uses or 0, families or 0


def count_groups(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(_t("groups"))) or 0


def testers(db: Session) -> list[dict]:
    users = _t("users")
    q = (
        select(
            users.c.id,
            users.c.name,
            users.c.login_id,
            users.c.tester_consent_at.label("consent_at"),
            users.c.tester_consent_version.label("consent_version"),
        )
        .where(users.c.tester_consent_at.is_not(None))
        .order_by(users.c.tester_consent_at.desc())
        .limit(LIST_LIMIT)
    )
    return [dict(r._mapping) for r in db.execute(q)]
