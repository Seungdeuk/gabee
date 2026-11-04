"""문의·신고 보내기와 내 문의 보기. 항상 로그인한 본인의 것만 다룬다."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_user
from app.shared.db import get_db

from . import service
from .schemas import TicketIn, TicketList, TicketOut

router = APIRouter(prefix="/support", tags=["support"])


@router.post("/tickets", response_model=TicketOut, status_code=201)
def create_ticket(
    body: TicketIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> TicketOut:
    """문의(inquiry)나 신고(report)를 보낸다. 사용자가 쓴 제목과 내용만 저장한다."""
    return service.create(db, user, body)


@router.get("/tickets/mine", response_model=TicketList)
def my_tickets(user: User = Depends(current_user), db: Session = Depends(get_db)) -> TicketList:
    """내가 보낸 문의·신고와 답변, 최근 순 최대 100건."""
    return service.list_mine(db, user)
