"""운영 관리자 API. 모든 경로는 `staff_user`(Bearer 정식 회원 + users.is_staff)를 거친다.
읽기 전용이다. 가족 데이터(문서·채팅·가계)의 내용은 다루지 않고 개수만 센다 — docs/requirements/admin.md 참고."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import staff_user
from app.shared.db import get_db

from . import service
from .schemas import AdminMeOut, FeaturesOut, GroupsOut, MembersOut, TestersOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/me", response_model=AdminMeOut)
def admin_me(user: User = Depends(staff_user)) -> AdminMeOut:
    """관리자 화면이 처음 열릴 때 부른다. 관리자가 아니면 404."""
    return service.me_out(user)


@router.get("/members", response_model=MembersOut, dependencies=[Depends(staff_user)])
def admin_members(db: Session = Depends(get_db)) -> MembersOut:
    """회원 수와 최근 가입자 목록. 이메일은 돌려주지 않는다."""
    return service.members(db)


@router.get("/groups", response_model=GroupsOut, dependencies=[Depends(staff_user)])
def admin_groups(db: Session = Depends(get_db)) -> GroupsOut:
    """가족 그룹 수와 구성원 수."""
    return service.groups(db)


@router.get("/features", response_model=FeaturesOut, dependencies=[Depends(staff_user)])
def admin_features(db: Session = Depends(get_db)) -> FeaturesOut:
    """기능별 최근 7일 사용 수와 그 전 7일 사용 수."""
    return service.features(db)


@router.get("/testers", response_model=TestersOut, dependencies=[Depends(staff_user)])
def admin_testers(db: Session = Depends(get_db)) -> TestersOut:
    """테스터 동의한 회원 목록."""
    return service.testers(db)
