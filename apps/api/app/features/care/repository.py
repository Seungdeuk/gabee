from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import CareEntry, CareItem, CareLocation, CareRecord


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


def has_items(db: Session, group_id: str) -> bool:
    """삭제한 항목까지 포함해서 확인한다(다 지워도 샘플을 다시 만들지 않기 위해)."""
    return db.scalar(select(CareItem.id).where(CareItem.group_id == group_id).limit(1)) is not None


def add_items(db: Session, items: list[CareItem]) -> None:
    db.add_all(items)
    db.commit()


def list_items(db: Session, group_id: str) -> list[CareItem]:
    return list(
        db.scalars(
            select(CareItem)
            .where(CareItem.group_id == group_id, CareItem.deleted_at.is_(None))
            .order_by(CareItem.scheduled_time, CareItem.sort_order)
        )
    )


def get_item(db: Session, group_id: str, item_id: str) -> CareItem | None:
    return db.scalar(
        select(CareItem).where(
            CareItem.id == item_id, CareItem.group_id == group_id, CareItem.deleted_at.is_(None)
        )
    )


def max_sort_order(db: Session, group_id: str) -> int:
    return db.scalar(
        select(func.coalesce(func.max(CareItem.sort_order), -1)).where(
            CareItem.group_id == group_id
        )
    )


def get_entry(db: Session, item_id: str, date: str) -> CareEntry | None:
    return db.scalar(select(CareEntry).where(CareEntry.item_id == item_id, CareEntry.date == date))


def entries_on(db: Session, group_id: str, date: str) -> dict[str, CareEntry]:
    rows = db.scalars(
        select(CareEntry).where(CareEntry.group_id == group_id, CareEntry.date == date)
    )
    return {e.item_id: e for e in rows}


def save_obj(db: Session, obj):
    db.add(obj)
    db.commit()
    return obj


def add_locations(db: Session, rows: list[CareLocation]) -> None:
    db.add_all(rows)
    db.commit()


def latest_location(db: Session, user_id: str, since) -> CareLocation | None:
    return db.scalar(
        select(CareLocation)
        .where(CareLocation.user_id == user_id, CareLocation.recorded_at >= since)
        .order_by(CareLocation.recorded_at.desc())
        .limit(1)
    )


def delete_user_locations(db: Session, user_id: str) -> int:
    n = db.query(CareLocation).filter(CareLocation.user_id == user_id).delete()
    db.commit()
    return n


def purge_locations_before(db: Session, cutoff) -> int:
    n = db.query(CareLocation).filter(CareLocation.recorded_at < cutoff).delete()
    db.commit()
    return n
