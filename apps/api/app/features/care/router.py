from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import service
from .schemas import PutResult, RecordOut, RecordPut, TodaySummary

router = APIRouter(prefix="/care", tags=["care"])


@router.put("/records", response_model=PutResult)
def put_record(
    body: RecordPut,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PutResult:
    """같은 날 같은 종류의 기록이 있으면 덮어쓴다."""
    return service.put(db, group_id, user.id, body)


@router.get("/records", response_model=list[RecordOut])
def list_records(
    date: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[RecordOut]:
    return service.list_day(db, group_id, date)


@router.get("/summary/today", response_model=TodaySummary)
def summary_today(
    group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> TodaySummary:
    return service.today_summary(db, group_id)
