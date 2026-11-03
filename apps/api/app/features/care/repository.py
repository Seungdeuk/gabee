from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CareLocation


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
