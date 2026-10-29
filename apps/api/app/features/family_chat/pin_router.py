"""고정 메시지(공지) 엔드포인트. family_chat 라우터에 포함되어 /family-chat/pins 아래로 열린다. AI 를 부르지 않는다."""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import pin_service
from .pin_schemas import PinCreate, PinItem, PinResult, PinsOut

router = APIRouter(prefix="/pins")

ROOM_ID = Query(None, max_length=32, description="대화방 id. 없으면 가족 전체방")


@router.get("", response_model=PinsOut)
def list_pins(
    room_id: str | None = ROOM_ID,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PinsOut:
    """이 방에 고정된 메시지(최근 고정 2개, 고정 시각 최신순)."""
    return pin_service.list_pins(db, user, group_id, room_id)


@router.post("", response_model=PinResult)
def pin_message(
    body: PinCreate,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PinResult:
    """메시지를 고정한다(방 안의 누구나). 이미 고정돼 있으면 그대로 두고 already_pinned=true.
    방당 최대 2개라 3번째면 가장 오래된 고정이 풀리고 그 메시지 id 가 replaced_message_id 로 온다."""
    return pin_service.pin(db, user, group_id, body.message_id, body.room_id)


@router.put("/{message_id}/hide", response_model=PinItem)
def hide_pin(
    message_id: int,
    room_id: str | None = ROOM_ID,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PinItem:
    """이 공지를 나만 숨긴다(다른 구성원에게는 그대로 보인다, 이미 숨겼어도 같은 결과). 올라가 있지 않으면 404."""
    return pin_service.hide(db, user, group_id, message_id, room_id, True)


@router.delete("/{message_id}/hide", response_model=PinItem)
def show_pin(
    message_id: int,
    room_id: str | None = ROOM_ID,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PinItem:
    """숨겼던 공지를 다시 보이게 한다(숨기지 않았어도 같은 결과)."""
    return pin_service.hide(db, user, group_id, message_id, room_id, False)


@router.delete("/{message_id}", status_code=204)
def unpin_message(
    message_id: int,
    room_id: str | None = ROOM_ID,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Response:
    """고정을 푼다(방 안의 누구나). 메시지는 그대로 남는다."""
    pin_service.unpin(db, user, group_id, message_id, room_id)
    return Response(status_code=204)
