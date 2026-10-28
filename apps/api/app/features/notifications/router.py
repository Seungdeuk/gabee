"""내 알림 조회·읽음 API. 항상 로그인한 본인의 알림만 다루며 그룹 id 는 요청에서 받지 않는다."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_user
from app.shared.db import get_db

from . import service
from .schemas import (
    Kind,
    NotificationList,
    NotificationOut,
    ReadAllBody,
    ReadAllResult,
    UnreadCount,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationList)
def list_notifications(
    kind: Kind | None = None,
    limit: int = Query(30, ge=1, le=100),
    cursor: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> NotificationList:
    """내 알림을 최신순으로. kind 로 분류를 거르고 cursor(이전 응답의 next_cursor)로 이어 본다."""
    return service.list_notifications(db, user, kind, limit, cursor)


@router.get("/unread-count", response_model=UnreadCount)
def unread_count(user: User = Depends(current_user), db: Session = Depends(get_db)) -> UnreadCount:
    """안 읽은 알림 개수(전체와 분류별)."""
    return service.unread_count(db, user)


@router.post("/read-all", response_model=ReadAllResult)
def read_all(
    body: ReadAllBody | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ReadAllResult:
    """안 읽은 알림을 모두 읽음 처리한다. kind 를 주면 그 분류만."""
    return service.read_all(db, user, body.kind if body else None)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def read_one(
    notification_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> NotificationOut:
    """알림 하나를 읽음 처리한다(이미 읽었으면 그대로). 남의 알림은 404."""
    return service.read_one(db, user, notification_id)
