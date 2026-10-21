import uuid
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import repository as repo
from .models import KINDS, CareRecord
from .schemas import PutResult, RecordOut, RecordPut, TodaySummary

KST = timezone(timedelta(hours=9))


def today_kst() -> str:
    return datetime.now(KST).date().isoformat()


def _out(r: CareRecord) -> RecordOut:
    return RecordOut(
        id=r.id,
        subject=r.subject,
        kind=r.kind,
        value=r.value,
        note=r.note,
        date=r.date,
        created_by=r.created_by,
    )


def put(db: Session, group_id: str, user_id: str, body: RecordPut) -> PutResult:
    day = (body.date or datetime.now(KST).date()).isoformat()
    existing = repo.find(db, group_id, body.subject.strip(), body.kind, day)
    if existing:
        existing.value, existing.note, existing.created_by = body.value, body.note, user_id
        existing.updated_at = datetime.now(UTC)
        return PutResult(record=_out(repo.save(db, existing)), replaced=True)
    record = CareRecord(
        id=uuid.uuid4().hex[:12],
        group_id=group_id,
        subject=body.subject.strip(),
        kind=body.kind,
        value=body.value,
        note=body.note,
        date=day,
        created_by=user_id,
    )
    return PutResult(record=_out(repo.save(db, record)), replaced=False)


def list_day(db: Session, group_id: str, day: str | None) -> list[RecordOut]:
    return [_out(r) for r in repo.list_day(db, group_id, day or today_kst())]


def today_summary(db: Session, group_id: str) -> TodaySummary:
    day = today_kst()
    records = [_out(r) for r in repo.list_day(db, group_id, day)]
    done = {r.kind for r in records}
    return TodaySummary(date=day, records=records, missing=[k for k in KINDS if k not in done])
