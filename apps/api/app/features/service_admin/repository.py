"""관리자 집계용 조회(쓰기는 문의·신고 상태·답변과 공지사항뿐). 다른 기능의 모델 파일을 import 하지 않고 공용 메타데이터의 표로 센다.
가족 데이터의 내용(채팅 글, 일정 제목, 금액 등)은 읽지 않고 개수와 시각만 쓴다."""

import uuid
from datetime import datetime

from sqlalchemy import Table, case, delete, func, insert, select, update
from sqlalchemy.orm import Session

from app.shared.db import Base

LIST_LIMIT = 200

# 사용자 요청이 아닌 표식 행(중첩 호출·한도 거절)은 요청 수에서 뺀다
MARKER_STATUSES = ("nested", "rejected")
LIMIT_CODES = ("ai_daily_limit_user", "ai_daily_limit_group")


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
            users.c.email_verified_at.is_not(None).label("email_verified"),
            family.c.user_id.is_not(None).label("has_family"),
            last_login.c.last_login_at,
        )
        .outerjoin(family, family.c.user_id == users.c.id)
        .outerjoin(last_login, last_login.c.user_id == users.c.id)
        .order_by(users.c.created_at.desc())
        .limit(LIST_LIMIT)
    )
    return [dict(r._mapping) for r in db.execute(q)]


def member_totals(db: Session, since_active: datetime) -> tuple[int, int, int]:
    """(since_active 이후 토큰을 받은 사람 수, 가족이 없는 사람 수, 이메일 인증한 사람 수)."""
    users, members, tokens = _t("users"), _t("group_members"), _t("refresh_tokens")
    active = db.scalar(
        select(func.count(tokens.c.user_id.distinct())).where(tokens.c.issued_at >= since_active)
    )
    no_family = db.scalar(
        select(func.count())
        .select_from(users)
        .outerjoin(members, members.c.user_id == users.c.id)
        .where(members.c.user_id.is_(None))
    )
    verified = db.scalar(
        select(func.count()).select_from(users).where(users.c.email_verified_at.is_not(None))
    )
    return active or 0, no_family or 0, verified or 0


def groups_with_counts(db: Session) -> tuple[int, list[dict]]:
    groups, members, users = _t("groups"), _t("group_members"), _t("users")
    join_reqs, ai = _t("join_requests"), _t("ai_group_settings")
    waiting = (
        select(join_reqs.c.group_id, func.count().label("pending"))
        .where(join_reqs.c.status == "pending")
        .group_by(join_reqs.c.group_id)
        .subquery()
    )
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
            func.coalesce(waiting.c.pending, 0).label("pending"),
            func.coalesce(ai.c.enabled, False).label("ai_enabled"),
            groups.c.created_at,
        )
        .outerjoin(size, size.c.group_id == groups.c.id)
        .outerjoin(waiting, waiting.c.group_id == groups.c.id)
        .outerjoin(ai, ai.c.group_id == groups.c.id)
        .outerjoin(users, users.c.id == groups.c.owner_id)
        .order_by(groups.c.created_at.desc())
    )
    rows = [dict(r._mapping) for r in db.execute(q)]
    return len(rows), rows


def join_and_ai_totals(db: Session) -> tuple[int, datetime | None, int]:
    """(승인 대기 수, 가장 오래된 대기 요청 시각, AI 를 켠 가족 수)."""
    join_reqs, ai = _t("join_requests"), _t("ai_group_settings")
    pending, oldest = db.execute(
        select(func.count(), func.min(join_reqs.c.requested_at)).where(
            join_reqs.c.status == "pending"
        )
    ).one()
    enabled = db.scalar(select(func.count()).select_from(ai).where(ai.c.enabled.is_(True)))
    return pending or 0, oldest, enabled or 0


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


def count_ai_requests(db: Session, since: datetime, until: datetime | None = None) -> int:
    """ai_usage_logs 의 요청 수(1행 = 사용자 요청 1번, 캐시 적중·오류 포함, nested·rejected 표식 제외)."""
    logs = _t("ai_usage_logs")
    q = (
        select(func.count())
        .select_from(logs)
        .where(logs.c.created_at >= since, logs.c.status.not_in(MARKER_STATUSES))
    )
    if until is not None:
        q = q.where(logs.c.created_at < until)
    return db.scalar(q) or 0


def ai_requests_by_feature(db: Session, since: datetime) -> list[tuple[str, int, int]]:
    """기능별 (직접 쓴 수, 메인 AI 비서가 안에서 부른 수), 합계 많은 순. 기능별로는 불린 에이전트도 센다(한도 거절은 뺀다)."""
    logs = _t("ai_usage_logs")
    via = func.sum(case((logs.c.status == "nested", 1), else_=0))
    q = (
        select(logs.c.feature, func.count() - via, via)
        .where(logs.c.created_at >= since, logs.c.status != "rejected")
        .group_by(logs.c.feature)
        .order_by(func.count().desc())
    )
    return [(feature, direct, via or 0) for feature, direct, via in db.execute(q)]


def ai_requests_by_group(db: Session, since: datetime) -> list[dict]:
    """가족별 요청 수·오류 수(많은 순)."""
    logs, groups = _t("ai_usage_logs"), _t("groups")
    total = func.count()
    q = (
        select(
            logs.c.group_id,
            func.max(groups.c.name).label("name"),
            total.label("requests"),
            func.coalesce(func.sum(case((logs.c.status == "error", 1), else_=0)), 0).label(
                "errors"
            ),
        )
        .select_from(logs)
        .outerjoin(groups, groups.c.id == logs.c.group_id)
        .where(logs.c.created_at >= since, logs.c.status.not_in(MARKER_STATUSES))
        .group_by(logs.c.group_id)
        .order_by(total.desc())
        .limit(LIST_LIMIT)
    )
    return [dict(r._mapping) for r in db.execute(q)]


def ai_requests_by_user(db: Session, since: datetime) -> list[dict]:
    """사용자별 요청 수·오류 수(많은 순)."""
    logs, users = _t("ai_usage_logs"), _t("users")
    total = func.count()
    q = (
        select(
            logs.c.user_id,
            func.max(users.c.name).label("name"),
            func.max(users.c.login_id).label("login_id"),
            total.label("requests"),
            func.coalesce(func.sum(case((logs.c.status == "error", 1), else_=0)), 0).label(
                "errors"
            ),
        )
        .select_from(logs)
        .outerjoin(users, users.c.id == logs.c.user_id)
        .where(logs.c.created_at >= since, logs.c.status.not_in(MARKER_STATUSES))
        .group_by(logs.c.user_id)
        .order_by(total.desc())
        .limit(LIST_LIMIT)
    )
    return [dict(r._mapping) for r in db.execute(q)]


def ai_limit_hits(db: Session, since: datetime) -> list[dict]:
    """일일 한도에 막힌 거절 기록을 사용자별로(날짜 계산은 서비스에서). 시각 목록을 함께 준다."""
    logs, users, groups = _t("ai_usage_logs"), _t("users"), _t("groups")
    q = (
        select(logs.c.user_id, logs.c.group_id, logs.c.created_at)
        .where(
            logs.c.created_at >= since,
            logs.c.status == "rejected",
            logs.c.error_code.in_(LIMIT_CODES),
        )
        .order_by(logs.c.created_at.desc())
    )
    hits = [dict(r._mapping) for r in db.execute(q)]
    if not hits:
        return []
    names = {
        uid: name
        for uid, name in db.execute(
            select(users.c.id, users.c.name).where(users.c.id.in_({h["user_id"] for h in hits}))
        )
    }
    group_names = {
        gid: name
        for gid, name in db.execute(
            select(groups.c.id, groups.c.name).where(groups.c.id.in_({h["group_id"] for h in hits}))
        )
    }
    for h in hits:
        h["name"] = names.get(h["user_id"])
        h["group_name"] = group_names.get(h["group_id"])
    return hits


def support_tickets(db: Session) -> list[dict]:
    """문의·신고 최근순(최대 200). 보낸 사람 이름·아이디와 가족 이름을 붙인다."""
    tickets, users, groups = _t("support_tickets"), _t("users"), _t("groups")
    q = (
        select(
            tickets,
            users.c.name.label("user_name"),
            users.c.login_id,
            groups.c.name.label("group_name"),
        )
        .outerjoin(users, users.c.id == tickets.c.user_id)
        .outerjoin(groups, groups.c.id == tickets.c.group_id)
        .order_by(tickets.c.created_at.desc(), tickets.c.id.desc())
        .limit(LIST_LIMIT)
    )
    return [dict(r._mapping) for r in db.execute(q)]


def support_counts(db: Session) -> dict[str, int]:
    """상태별 건수와 전체 신고 수."""
    tickets = _t("support_tickets")
    counts = {
        status: n
        for status, n in db.execute(
            select(tickets.c.status, func.count()).group_by(tickets.c.status)
        )
    }
    counts["report"] = db.scalar(select(func.count()).where(tickets.c.kind == "report")) or 0
    return counts


def get_support_ticket(db: Session, ticket_id: str) -> dict | None:
    """답변 알림에 필요한 보낸 사람과 지금 답변. 없는 번호면 None."""
    tickets = _t("support_tickets")
    row = db.execute(
        select(tickets.c.user_id, tickets.c.answer).where(tickets.c.id == ticket_id)
    ).first()
    return dict(row._mapping) if row else None


def update_support_ticket(db: Session, ticket_id: str, values: dict) -> bool:
    """상태·답변을 바꾼다. 없는 번호면 False. 커밋은 부르는 쪽이 한다(알림과 함께 저장)."""
    tickets = _t("support_tickets")
    done = db.execute(update(tickets).where(tickets.c.id == ticket_id).values(**values)).rowcount
    return bool(done)


NOTICE_COLUMNS = ("id", "category", "title", "body", "created_at", "updated_at")


def notices(db: Session) -> list[dict]:
    """공지사항 최근순(최대 200). 쓴 관리자 id 는 화면에 보내지 않는다."""
    t = _t("notices")
    q = (
        select(*(t.c[c] for c in NOTICE_COLUMNS))
        .order_by(t.c.created_at.desc(), t.c.id.desc())
        .limit(LIST_LIMIT)
    )
    return [dict(r._mapping) for r in db.execute(q)]


def add_notice(db: Session, values: dict) -> dict:
    """공지 한 줄을 넣고 그 줄을 돌려준다. 커밋은 부르는 쪽이 한다."""
    t = _t("notices")
    row = {"id": uuid.uuid4().hex[:12], **values}
    db.execute(insert(t).values(**row))
    return {c: row[c] for c in NOTICE_COLUMNS}


def update_notice(db: Session, notice_id: str, values: dict) -> bool:
    t = _t("notices")
    return bool(db.execute(update(t).where(t.c.id == notice_id).values(**values)).rowcount)


def delete_notice(db: Session, notice_id: str) -> bool:
    t = _t("notices")
    return bool(db.execute(delete(t).where(t.c.id == notice_id)).rowcount)
