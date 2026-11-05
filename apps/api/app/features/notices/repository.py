from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Notice

LIST_LIMIT = 100


def latest(db: Session) -> list[Notice]:
    q = select(Notice).order_by(Notice.created_at.desc(), Notice.id.desc()).limit(LIST_LIMIT)
    return list(db.scalars(q))
