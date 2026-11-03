"""데일리 체크 API. `schedule/router.py` 에서 `/schedule/check` 아래로 붙는다.

- 모든 API 는 로그인과 현재 가족 그룹이 필요하다(current_user·current_group_id).
- 기능 준비 점검: 체크 테이블(events_check_*)이 준비되지 않은 DB 면 이 API 만 503(schedule_check). 일정의 나머지는 그대로다.
- 순서 주의: `PUT /items/order` 는 `PUT /items/{item_id}` 보다 먼저 등록해야 'order' 가 id 로 잡히지 않는다.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db
from app.shared.schema_gate import schema_ready

from . import check as service
from .check_schemas import (
    CheckCheerCreate,
    CheckCheerOut,
    CheckEntryBody,
    CheckItemCreate,
    CheckItemOrder,
    CheckItemOut,
    CheckItemUpdate,
    CheckMemberSummary,
    CheckMemberToday,
    CheckSettingsIn,
    CheckSettingsOut,
)

router = APIRouter(
    prefix="/check",
    dependencies=[Depends(schema_ready("schedule_check"))],
)


# ---------------------------------------------------------------- 내 습관
@router.get("/items", response_model=list[CheckItemOut])
def list_items(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[dict]:
    return service.list_items(db, user.id)


@router.post("/items", response_model=CheckItemOut, status_code=201)
def create_item(
    body: CheckItemCreate,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    return service.create_item(db, user.id, body)


@router.put("/items/order", response_model=list[CheckItemOut])
def reorder_items(
    body: CheckItemOrder,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[dict]:
    return service.reorder_items(db, user.id, body.ids)


@router.put("/items/{item_id}", response_model=CheckItemOut)
def update_item(
    item_id: str,
    body: CheckItemUpdate,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    return service.update_item(db, user.id, item_id, body)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(
    item_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Response:
    service.delete_item(db, user.id, item_id)
    return Response(status_code=204)


@router.put("/items/{item_id}/entry", response_model=CheckItemOut)
def set_entry(
    item_id: str,
    body: CheckEntryBody,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    return service.set_entry(db, user.id, item_id, body)


# ---------------------------------------------------------------- 가족
@router.get("/members/summary", response_model=list[CheckMemberSummary])
def members_summary(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[dict]:
    return service.members_summary(db, group_id)


@router.get("/members/{user_id}/today", response_model=CheckMemberToday)
def member_today(
    user_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    return service.member_today(db, group_id, user_id)


# ---------------------------------------------------------------- 응원
@router.post("/cheers", response_model=CheckCheerOut, status_code=201)
def send_cheer(
    body: CheckCheerCreate,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    return service.send_cheer(db, group_id, user.id, body)


@router.get("/cheers", response_model=list[CheckCheerOut])
def list_cheers(
    direction: Literal["received", "sent"] = "received",
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[dict]:
    return service.list_cheers(db, user.id, direction)


@router.put("/cheers/{cheer_id}/thanked", response_model=CheckCheerOut)
def set_cheer_thanked(
    cheer_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    """고마워 보내기(본문 없음). 처음 한 번만 시각을 남기고, 다시 보내도 그대로다."""
    return service.set_thanked(db, user.id, cheer_id)


@router.put("/cheers/{cheer_id}/closed", response_model=CheckCheerOut)
def close_cheer(
    cheer_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    return service.close_cheer(db, user.id, cheer_id)


# ---------------------------------------------------------------- 설정
@router.get("/settings", response_model=CheckSettingsOut)
def get_settings(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    return service.get_settings(db, user.id)


@router.put("/settings", response_model=CheckSettingsOut)
def set_settings(
    body: CheckSettingsIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    return service.set_settings(db, user.id, body)
