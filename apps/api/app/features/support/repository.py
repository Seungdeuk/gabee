from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import SupportTicket

MINE_LIMIT = 100


def add(db: Session, ticket: SupportTicket) -> SupportTicket:
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def list_mine(db: Session, user_id: str) -> list[SupportTicket]:
    q = (
        select(SupportTicket)
        .where(SupportTicket.user_id == user_id)
        .order_by(SupportTicket.created_at.desc(), SupportTicket.id.desc())
        .limit(MINE_LIMIT)
    )
    return list(db.scalars(q))
