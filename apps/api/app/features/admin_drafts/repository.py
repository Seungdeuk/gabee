"""초안 대기함 DB 접근. 알림·문의·공지 표는 다른 기능의 모델을 가져오지 않고 표 이름으로만 읽는다(service_admin 과 같은 방식)."""

import uuid
from datetime import datetime

from sqlalchemy import Table, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared.db import Base

from .models import AdminDraft

LIST_LIMIT = 100


def _t(name: str) -> Table:
    return Base.metadata.tables[name]


def recent_alerts(db: Session, since: datetime) -> list[dict]:
    """since 이후 생긴 관리자 알림(숫자만 든 문구). 오래된 것부터."""
    t = _t("admin_alert_log")
    rows = db.execute(
        select(t.c.key, t.c.rule, t.c.severity, t.c.message, t.c.menu, t.c.created_at)
        .where(t.c.created_at >= since)
        .order_by(t.c.created_at)
    )
    return [dict(r._mapping) for r in rows]


def ticket_counts(db: Session, since: datetime) -> dict[str, int]:
    """since 이후 들어온 문의·신고 수(종류별)."""
    t = _t("support_tickets")
    rows = db.execute(
        select(t.c.kind, func.count()).where(t.c.created_at >= since).group_by(t.c.kind)
    )
    return {kind: n for kind, n in rows}


def tickets_needing_reply(db: Session, limit: int) -> list[dict]:
    """답변이 없고 접수 상태인 문의 중 아직 답변 초안이 없는 것(오래된 것부터). 보낸 사람 칸은 읽지 않는다."""
    t = _t("support_tickets")
    drafted = select(AdminDraft.ticket_id).where(
        AdminDraft.kind == "reply", AdminDraft.ticket_id.is_not(None)
    )
    rows = db.execute(
        select(t.c.id, t.c.kind, t.c.title, t.c.body)
        .where(t.c.status == "new", t.c.answer.is_(None), t.c.id.not_in(drafted))
        .order_by(t.c.created_at)
        .limit(limit)
    )
    return [dict(r._mapping) for r in rows]


def last_notice_draft_at(db: Session, *, auto: bool) -> datetime | None:
    """가장 최근에 만든 공지 초안(auto=True 면 자동 공지)의 시각."""
    return db.scalar(
        select(func.max(AdminDraft.created_at)).where(
            AdminDraft.kind == "notice", AdminDraft.auto.is_(auto)
        )
    )


def add_draft(db: Session, draft: AdminDraft) -> bool:
    """같은 근거(kind, source_key)의 초안이 이미 있으면 넣지 않고 False."""
    try:
        with db.begin_nested():
            db.add(draft)
            db.flush()
    except IntegrityError:
        return False
    return True


def get_ticket(db: Session, ticket_id: str) -> dict | None:
    """문의 한 건의 종류·제목·내용(보낸 사람 칸은 읽지 않는다)."""
    t = _t("support_tickets")
    row = db.execute(
        select(t.c.id, t.c.kind, t.c.title, t.c.body).where(t.c.id == ticket_id)
    ).first()
    return dict(row._mapping) if row else None


def get_by_source(db: Session, kind: str, source_key: str) -> AdminDraft | None:
    return db.scalar(
        select(AdminDraft).where(AdminDraft.kind == kind, AdminDraft.source_key == source_key)
    )


def has_draft(db: Session, kind: str, source_key: str) -> bool:
    return (
        db.scalar(
            select(AdminDraft.id).where(
                AdminDraft.kind == kind, AdminDraft.source_key == source_key
            )
        )
        is not None
    )


def pending(db: Session) -> list[AdminDraft]:
    """대기 중인 초안(최근순)."""
    return list(
        db.scalars(
            select(AdminDraft)
            .where(AdminDraft.status == "pending")
            .order_by(AdminDraft.created_at.desc())
            .limit(LIST_LIMIT)
        )
    )


def recent_auto_notices(db: Session, limit: int = 5) -> list[AdminDraft]:
    return list(
        db.scalars(
            select(AdminDraft)
            .where(AdminDraft.auto.is_(True))
            .order_by(AdminDraft.created_at.desc())
            .limit(limit)
        )
    )


def set_status(db: Session, draft_id: str, status: str, now: datetime) -> bool:
    result = db.execute(
        update(AdminDraft).where(AdminDraft.id == draft_id).values(status=status, updated_at=now)
    )
    return result.rowcount > 0


def add_notice(db: Session, category: str, title: str, body: str, now: datetime) -> str:
    """공지 표에 한 줄 넣는다(자동 공지). 쓴 사람은 비워 둔다(사람이 아니라 자동)."""
    notice_id = uuid.uuid4().hex[:12]
    db.execute(
        insert(_t("notices")).values(
            id=notice_id,
            category=category,
            title=title,
            body=body,
            created_by=None,
            created_at=now,
            updated_at=now,
        )
    )
    return notice_id
