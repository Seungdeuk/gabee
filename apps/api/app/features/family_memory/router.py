"""AI 추억 동의·설정 API(PR1). 이미지 분석·카드는 이 PR 에 없다. 그룹은 요청에서 받지 않고 `current_group_id` 로만 정한다."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import service
from .schemas import (
    ConsentIn,
    ExclusionIn,
    ExclusionOut,
    FamilyEnabledIn,
    MemoryStateOut,
)

router = APIRouter(prefix="/family-memory", tags=["family-memory"])


@router.get("/settings", response_model=MemoryStateOut)
def get_settings(
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MemoryStateOut:
    """서버 스위치·가족 설정·내 동의 상태. 가족 구성원 누구나 본다."""
    return service.get_state(db, user, group_id)


@router.put("/settings", response_model=MemoryStateOut)
def put_settings(
    body: FamilyEnabledIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MemoryStateOut:
    """가족 기능을 켜고 끈다(소유자·관리자만, member 는 403). 켜는 것은 서버 스위치가 켜져 있을 때만."""
    return service.set_family_enabled(db, user, group_id, body.enabled)


@router.put("/consent", response_model=MemoryStateOut)
def put_consent(
    body: ConsentIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MemoryStateOut:
    """내 사진의 AI 분석에 동의하거나 철회한다(본인 것만). 철회는 항상 가능하고 즉시 효력이 생긴다."""
    return service.set_consent(db, user, group_id, body.consent)


@router.put("/consent/retro", response_model=MemoryStateOut)
def put_retro_consent(
    body: ConsentIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MemoryStateOut:
    """과거 사진 소급 분석 동의(별개, 기본 꺼짐). 이 단계에서는 동의 기록만 남기고 소급 분석 작업은 만들지 않는다."""
    return service.set_retro_consent(db, user, group_id, body.consent)


@router.put("/photos/{attachment_id}/exclusion", response_model=ExclusionOut)
def put_exclusion(
    attachment_id: str,
    body: ExclusionIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> ExclusionOut:
    """내가 올린 사진을 AI 분석에서 빼거나 다시 넣는다(업로더 본인만). 타임라인 노출과는 별개다."""
    return service.set_exclusion(db, user, group_id, attachment_id, body.excluded)
