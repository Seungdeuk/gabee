"""admin_alert_log 접근. 업무 규칙은 service.py 에 있고 여기서는 DB 만 다룬다."""

from datetime import datetime

from sqlalchemy import case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AdminAlertLog


def insert_if_absent(db: Session, row: AdminAlertLog) -> bool:
    """키가 아직 없을 때만 넣는다. 넣었으면 True, 이미 있으면(다른 점검이 먼저 넣었으면) False.
    savepoint 를 써서 실패해도 바깥 트랜잭션(다른 알림 넣기)은 살아 있다."""
    try:
        with db.begin_nested():
            db.add(row)
        return True
    except IntegrityError:
        return False


def get(db: Session, key: str) -> AdminAlertLog | None:
    return db.get(AdminAlertLog, key)


def list_rows(db: Session, limit: int) -> list[AdminAlertLog]:
    """확인 안 된 것 먼저, 같은 안에서는 최근 것 먼저."""
    stmt = (
        select(AdminAlertLog)
        .order_by(
            case((AdminAlertLog.acked_at.is_(None), 0), else_=1),
            AdminAlertLog.created_at.desc(),
        )
        .limit(limit)
    )
    return list(db.scalars(stmt))


def unacked_count(db: Session) -> int:
    stmt = select(AdminAlertLog.key).where(AdminAlertLog.acked_at.is_(None))
    return len(list(db.scalars(stmt)))


def mark_acked(db: Session, row: AdminAlertLog, by: str, now: datetime) -> None:
    """아직 확인 안 된 줄만 확인 처리한다. 이미 확인된 줄은 건드리지 않는다."""
    if row.acked_at is None:
        row.acked_at = now
        row.acked_by = by
        db.commit()
