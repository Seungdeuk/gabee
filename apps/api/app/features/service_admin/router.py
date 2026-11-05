"""서비스 관리자 API. 모든 경로는 `require_operator("service_admin")`(Bearer 정식 회원 + SERVICE_ADMIN_USER_IDS 허용 목록)를 거친다.
문의·신고의 상태·답변 바꾸기와 공지사항 쓰기·고치기·지우기만 쓰기이고 나머지는 읽기 전용이다. 가족 데이터(문서·채팅·가계)의 내용은 다루지 않고 개수만 센다 — docs/requirements/admin.md 참고."""

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
    AdminNoticeIn,
    AdminNoticeRow,
    AdminNoticesOut,
    AdminTicketsOut,
    AdminTicketUpdate,
    FeaturesOut,
    GroupsOut,
    MembersOut,
)

router = APIRouter(prefix="/admin/service", tags=["service-admin"])
service_admin = require_operator("service_admin")
# 문의·신고 표가 아직 없는 DB 에서는 그 경로만 503
SUPPORT = [Depends(service_admin), Depends(schema_ready("support"))]
NOTICES = [Depends(schema_ready("notices"))]  # 공지 표가 없는 DB 에서는 공지 경로만 503


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


@router.get(
    "/notices", response_model=AdminNoticesOut, dependencies=[Depends(service_admin), *NOTICES]
)
def admin_notices(db: Session = Depends(get_db)) -> AdminNoticesOut:
    """공지사항 최근순 목록(앱과 같은 순서)."""
    return service.notices(db)


@router.post("/notices", response_model=AdminNoticeRow, status_code=201, dependencies=NOTICES)
def admin_create_notice(
    body: AdminNoticeIn, user: User = Depends(service_admin), db: Session = Depends(get_db)
) -> AdminNoticeRow:
    """공지를 쓴다. 저장하면 바로 앱 공지사항에 보인다(알림은 보내지 않는다)."""
    return service.create_notice(db, user, body)


@router.put(
    "/notices/{notice_id}", status_code=204, dependencies=[Depends(service_admin), *NOTICES]
)
def admin_update_notice(notice_id: str, body: AdminNoticeIn, db: Session = Depends(get_db)) -> None:
    """공지의 종류·제목·내용을 통째로 고친다. 없는 번호면 404."""
    service.update_notice(db, notice_id, body)


@router.delete(
    "/notices/{notice_id}", status_code=204, dependencies=[Depends(service_admin), *NOTICES]
)
def admin_delete_notice(notice_id: str, db: Session = Depends(get_db)) -> None:
    """공지를 지운다(되돌릴 수 없다). 없는 번호면 404."""
    service.delete_notice(db, notice_id)
