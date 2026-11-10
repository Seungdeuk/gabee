"""메시지-일정·할 일 연결 엔드포인트. family_chat 라우터에 포함되어 /family-chat/links 아래로 열린다. AI 를 부르지 않는다."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import link_service
from .link_schemas import LinkCreate, LinkOut, LinksOut

router = APIRouter(prefix="/links")

ROOM_ID = Query(None, max_length=32, description="대화방 id. 없으면 가족 전체방")


@router.get("", response_model=LinksOut)
def list_links(
    room_id: str | None = ROOM_ID,
    kind: Literal["event", "todo"] | None = Query(None),
    target_id: str | None = Query(None, min_length=1, max_length=32),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> LinksOut:
    """이 방의 연결을 최신순으로. kind·target_id 로 거를 수 있다(일정 화면이 원본 대화를 찾을 때 target_id 를 쓴다)."""
    return link_service.list_links(db, user, group_id, room_id, kind, target_id, limit)


@router.post("", response_model=LinkOut, status_code=201)
def create_link(
    body: LinkCreate,
    response: Response,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> LinkOut:
    """메시지와 등록한 일정·할 일을 연결한다(방 안의 누구나). 이미 있으면 새로 만들지 않고 기존 연결을 200 으로 돌려준다.
    상대가 나간 1:1 방이면 409 `peer_left_room`."""
    out, created = link_service.create(db, user, group_id, body)
    if not created:
        response.status_code = 200
    return out


@router.delete("/{link_id}", status_code=204)
def delete_link(
    link_id: str,
    room_id: str | None = ROOM_ID,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Response:
    """연결을 지운다(만든 사람만). 메시지·일정·할 일은 그대로 남는다."""
    link_service.delete(db, user, group_id, link_id, room_id)
    return Response(status_code=204)
