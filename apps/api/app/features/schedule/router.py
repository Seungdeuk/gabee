from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import service
from .agent.router import router as agent_router
from .models import Event
from .schemas import EventCreate, EventOut

router = APIRouter(prefix="/schedule", tags=["schedule"])
router.include_router(agent_router)


@router.get("/events", response_model=list[EventOut])
def list_events(
    include_past: bool = False,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[Event]:
    return service.upcoming(db, group_id, user.id, include_past)


@router.post("/events", response_model=EventOut, status_code=201)
def create_event(
    body: EventCreate,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Event:
    return service.create(db, group_id, user.id, body)


@router.post("/events/{event_id}/confirm", response_model=EventOut)
def confirm_event(
    event_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Event:
    return service.confirm(db, group_id, user.id, event_id)


@router.delete("/events/{event_id}", status_code=204)
def delete_event(
    event_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Response:
    service.remove(db, group_id, user.id, event_id)
    return Response(status_code=204)
