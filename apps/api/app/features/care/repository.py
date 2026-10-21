from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CareRecord


def find(db: Session, group_id: str, subject: str, kind: str, date: str) -> CareRecord | None:
    return db.scalar(
        select(CareRecord).where(
            CareRecord.group_id == group_id,
            CareRecord.subject == subject,
            CareRecord.kind == kind,
            CareRecord.date == date,
        )
    )


def save(db: Session, record: CareRecord) -> CareRecord:
    db.add(record)
    db.commit()
    return record


def list_day(db: Session, group_id: str, date: str) -> list[CareRecord]:
    return list(
        db.scalars(
            select(CareRecord)
            .where(CareRecord.group_id == group_id, CareRecord.date == date)
            .order_by(CareRecord.subject, CareRecord.kind)
        )
    )
