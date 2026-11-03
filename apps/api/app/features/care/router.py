from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.config import settings
from app.shared.db import get_db
from app.shared.errors import ApiError

from . import service
from .schemas import (
    ConsentOut,
    ConsentSet,
    LocationBatch,
    LocationSaved,
    LocationsLatest,
)

router = APIRouter(prefix="/care", tags=["care"])

# 위치 동의 철회·조회는 저장된 내 위치를 지우는 길이라 돌봄 API 가 닫혀 있어도 연다(켜기는 서비스가 location_disabled 로 막는다)
_OPEN_WHEN_CLOSED = "/care/location/consent"


def require_care_api(request: Request) -> None:
    """돌봄 서버 API 스위치(CARE_API_ENABLED). 닫혀 있으면 /care/* 요청을 403 care_disabled 로 막는다."""
    if settings.care_api_enabled or request.url.path == _OPEN_WHEN_CLOSED:
        return
    raise ApiError(403, "care_disabled", "돌봄 기능은 지금 사용할 수 없어요")


# 데일리 체크(항목·기록·추천·식단)와 돌봄 에이전트 라우트는 지갑 탭 개편 때 지웠다. 위치 공유만 남아 있다(보류, 꺼짐).


@router.get("/location/consent", response_model=ConsentOut)
def get_location_consent(user=Depends(current_user)) -> ConsentOut:
    """내 위치 공유 동의 상태."""
    return service.location_consent(user)


@router.put("/location/consent", response_model=ConsentOut)
def put_location_consent(
    body: ConsentSet, user=Depends(current_user), db: Session = Depends(get_db)
) -> ConsentOut:
    """위치 공유에 동의하거나 철회한다. 철회하면 저장된 내 위치를 바로 지운다."""
    return service.set_consent(db, user, body.consent)


@router.post("/locations", response_model=LocationSaved, status_code=201)
def post_locations(
    body: LocationBatch,
    user=Depends(current_user),
    _: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> LocationSaved:
    """동의한 사람이 위치를 보낸다(앱이 주기적으로 보낸다). 동의하지 않았으면 403 consent_required."""
    return service.save_locations(db, user, body)


@router.get("/locations/latest", response_model=LocationsLatest)
def locations_latest(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> LocationsLatest:
    """가족 구성원의 최신 위치. 동의한 구성원의 위치만 좌표가 내려간다."""
    return service.latest_locations(db, group_id, user)
