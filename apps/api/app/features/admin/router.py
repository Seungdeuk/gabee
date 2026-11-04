"""서비스 관리자 API. 모든 경로는 `require_operator("service_admin")`(Bearer 정식 회원 + SERVICE_ADMIN_USER_IDS 허용 목록)를 거친다.
문의·신고의 상태·답변 바꾸기만 쓰기이고 나머지는 읽기 전용이다. 가족 데이터(문서·채팅·가계)의 내용은 다루지 않고 개수만 센다 — docs/requirements/admin.md 참고."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import require_operator
from app.shared.db import get_db
from app.shared.schema_gate import schema_ready

from . import service
from .schemas import (
    AdminAiUsageOut,
    AdminMeOut,
    AdminTicketsOut,
    AdminTicketUpdate,
    FeaturesOut,
    GroupsOut,
    MembersOut,
)

router = APIRouter(prefix="/admin", tags=["admin"])
service_admin = require_operator("service_admin")
# 문의·신고 표가 아직 없는 DB 에서는 그 경로만 503
SUPPORT = [Depends(service_admin), Depends(schema_ready("support"))]


@router.get("/me", response_model=AdminMeOut)
def admin_me(user: User = Depends(service_admin)) -> AdminMeOut:
    """관리자 화면이 처음 열릴 때 부른다. 허용 목록에 없으면 403 operator_required."""
    return service.me_out(user)


@router.get("/members", response_model=MembersOut, dependencies=[Depends(service_admin)])
def admin_members(db: Session = Depends(get_db)) -> MembersOut:
    """회원 수와 최근 가입자 목록. 이메일은 돌려주지 않는다."""
    return service.members(db)


@router.get("/groups", response_model=GroupsOut, dependencies=[Depends(service_admin)])
def admin_groups(db: Session = Depends(get_db)) -> GroupsOut:
    """가족 그룹 수와 구성원 수."""
    return service.groups(db)


@router.get("/features", response_model=FeaturesOut, dependencies=[Depends(service_admin)])
def admin_features(db: Session = Depends(get_db)) -> FeaturesOut:
    """기능별 최근 7일 사용 수와 그 전 7일 사용 수."""
    return service.features(db)


@router.get("/ai-usage", response_model=AdminAiUsageOut, dependencies=[Depends(service_admin)])
def admin_ai_usage(db: Session = Depends(get_db)) -> AdminAiUsageOut:
    """AI 기능 사용 요청 수(오늘·7일·30일, 하루별 14일, 기능별 30일). 대화 내용은 다루지 않는다."""
    return service.ai_usage(db)


@router.get("/support", response_model=AdminTicketsOut, dependencies=SUPPORT)
def admin_support(db: Session = Depends(get_db)) -> AdminTicketsOut:
    """문의·신고 목록과 상태별 건수. 사용자가 직접 쓴 글만 있다."""
    return service.support(db)


@router.patch("/support/{ticket_id}", status_code=204, dependencies=SUPPORT)
def admin_update_support(
    ticket_id: str, body: AdminTicketUpdate, db: Session = Depends(get_db)
) -> None:
    """상태(new/working/done)나 답변을 바꾼다. 없는 번호면 404."""
    service.update_support(db, ticket_id, body)
