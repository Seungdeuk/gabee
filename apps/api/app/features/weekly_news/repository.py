from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MemberWeeklyNews


def get_for_member(
    db: Session, group_id: str, user_id: str, week_start: date
) -> MemberWeeklyNews | None:
    """그 가족의 그 구성원의 그 주 저장본. 세 값이 모두 맞아야만 찾는다."""
    return db.scalar(
        select(MemberWeeklyNews).where(
            MemberWeeklyNews.group_id == group_id,
            MemberWeeklyNews.user_id == user_id,
            MemberWeeklyNews.week_start == week_start,
        )
    )
