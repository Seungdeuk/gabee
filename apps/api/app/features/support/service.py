from sqlalchemy.orm import Session

from app.features.family_group.models import User

from . import repository
from .models import SupportTicket
from .schemas import TicketIn, TicketList, TicketOut


def _out(t: SupportTicket) -> TicketOut:
    return TicketOut.model_validate(t, from_attributes=True)


def create(db: Session, user: User, body: TicketIn) -> TicketOut:
    ticket = SupportTicket(
        user_id=user.id,
        group_id=user.active_group_id,
        kind=body.kind,
        title=body.title.strip(),
        body=body.body.strip(),
    )
    return _out(repository.add(db, ticket))


def list_mine(db: Session, user: User) -> TicketList:
    return TicketList(rows=[_out(t) for t in repository.list_mine(db, user.id)])
