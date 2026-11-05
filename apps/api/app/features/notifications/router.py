"""내 알림 조회·읽음 API. 항상 로그인한 본인의 알림만 다루며 그룹 id 는 요청에서 받지 않는다."""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_user
from app.shared.db import get_db

from . import service
from .schemas import (
    Kind,
    NotificationList,
    NotificationOut,
    PushSettingsIn,
    PushSettingsOut,
    PushTokenDelete,
    PushTokenIn,
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


@router.get("/push-settings", response_model=PushSettingsOut)
def get_push_settings(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> PushSettingsOut:
    """내 푸시 설정(저장한 적이 없으면 기본값)."""
    return service.get_push_settings(db, user)


@router.put("/push-settings", response_model=PushSettingsOut)
def put_push_settings(
    body: PushSettingsIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> PushSettingsOut:
    """내 푸시 설정을 저장한다(켜기·끄기, 내용 표시 방식, 끈 분류, 방해금지 시간)."""
    return service.put_push_settings(db, user, body)


@router.put("/push-token", status_code=204)
def put_push_token(
    body: PushTokenIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    """이 기기의 푸시 토큰을 등록한다(같은 토큰이 이미 있으면 소유자·정보를 갱신)."""
    service.register_push_token(db, user, body)
    return Response(status_code=204)


@router.delete("/push-token", status_code=204)
def delete_push_token(
    body: PushTokenDelete, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    """이 기기의 푸시 토큰을 해제한다(로그아웃 때). 내 토큰만 지우고 없어도 204."""
    service.unregister_push_token(db, user, body)
    return Response(status_code=204)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def read_one(
    notification_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> NotificationOut:
    """알림 하나를 읽음 처리한다(이미 읽었으면 그대로). 남의 알림은 404."""
    return service.read_one(db, user, notification_id)
