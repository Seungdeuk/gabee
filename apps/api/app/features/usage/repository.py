"""usage_daily 접근. 언제·얼마나 더할지(업무 규칙)는 service.py 에 있고 여기서는 DB 만 다룬다."""

from datetime import date, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import DAY_SECONDS, UsageDaily


def _add_one(
    db: Session, user_id: str, day: date, tab: str, seconds: int, opens: int, now: datetime
) -> None:
    """한 줄에 더한다. 없으면 만든다. 동시에 두 요청이 같은 줄을 만들려 하면 기본키가 막고, 다시 읽어 더한다."""
    row = db.get(UsageDaily, (user_id, day, tab))
    if row is None:
        try:
            with db.begin_nested():
                db.add(
                    UsageDaily(
                        user_id=user_id,
                        day=day,
                        tab=tab,
                        seconds=min(seconds, DAY_SECONDS),
                        opens=opens,
                        updated_at=now,
                    )
                )
            return
        except IntegrityError:
            row = db.get(UsageDaily, (user_id, day, tab))
            if row is None:
                raise
    row.seconds = min((row.seconds or 0) + seconds, DAY_SECONDS)
    row.opens = (row.opens or 0) + opens
    row.updated_at = now


def add_usage(
    db: Session, user_id: str, day: date, rows: list[tuple[str, int, int]], now: datetime
) -> None:
    """(탭, 초, 실행 횟수) 목록을 그날 줄들에 더하고 한 번에 저장한다."""
    for tab, seconds, opens in rows:
        _add_one(db, user_id, day, tab, seconds, opens, now)
    db.commit()
