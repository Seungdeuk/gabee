"""가족 초대·가입 승인(PR 4-B) 엔드포인트. family_group 라우터에 포함되어 같은 /family-group 아래로 열린다.

권한(owner/admin) 판단은 전부 서버가 group_members.role 로 한다. 요청 본문에는 role 을 받는 곳이 없다."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.shared.auth import current_user
from app.shared.db import get_db

from . import join_service, service
from .join_schemas import InviteOut, InviteSettingsIn, JoinRequestOut, PendingJoinOut
from .models import User
from .schemas import GroupOut

router = APIRouter()


@router.post("/groups/invites/reissue", response_model=InviteOut)
def reissue_invite(user: User = Depends(current_user), db: Session = Depends(get_db)) -> InviteOut:
    """새 초대 코드를 만든다(기본 24시간·20명). 기존 코드는 폐기된다. 가족 관리자(owner/admin)만."""
    invite = join_service.reissue_invite(db, user)
    return InviteOut(
        invite_code=invite.code,
        expires_at=invite.expires_at,
        uses_left=service.invite_uses_left(invite),
    )


@router.put("/groups/invites/settings", response_model=GroupOut)
def update_invite_settings(
    body: InviteSettingsIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> GroupOut:
    """초대 코드로 들어온 사람을 바로 구성원으로 넣을지(자동 승인) 켜고 끈다. 가족 관리자만."""
    group_id = join_service.set_auto_approve(db, user, body.auto_approve)
    return service.group_out_by_id(db, group_id, user.id)


@router.post("/groups/invites/revoke", status_code=204)
def revoke_invite(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    """지금 쓸 수 있는 초대 코드를 모두 폐기한다. 가족 관리자만."""
    join_service.revoke_invite(db, user)
    return Response(status_code=204)


@router.get("/groups/me/join-requests", response_model=list[PendingJoinOut])
def pending_join_requests(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[PendingJoinOut]:
    """내 가족 그룹의 승인 대기 요청 목록. 가족 관리자만."""
    return [
        PendingJoinOut(
            id=req.id,
            user_id=applicant.id,
            user_name=applicant.name,
            user_role=applicant.role,
            requested_at=req.requested_at,
        )
        for req, applicant in join_service.pending_for_manager(db, user)
    ]


@router.get("/groups/join-requests/mine", response_model=JoinRequestOut | None)
def my_join_request(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> JoinRequestOut | None:
    """내가 낸 가장 최근 가입 요청(승인 대기·승인·거절·취소). 없으면 null."""
    found = join_service.latest_request(db, user)
    return service.join_request_out(*found) if found else None


@router.post("/groups/join-requests/{request_id}/approve", response_model=GroupOut)
def approve_join_request(
    request_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> GroupOut:
    """승인한다. 이때 비로소 구성원(member)이 된다. 가족 관리자만."""
    group_id = join_service.approve(db, user, request_id)
    return service.group_out_by_id(db, group_id, user.id)


@router.post("/groups/join-requests/{request_id}/reject", status_code=204)
def reject_join_request(
    request_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    """거절한다. 가족 관리자만."""
    join_service.reject(db, user, request_id)
    return Response(status_code=204)


@router.post("/groups/join-requests/{request_id}/cancel", status_code=204)
def cancel_join_request(
    request_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    """내 대기 요청을 취소한다."""
    join_service.cancel(db, user, request_id)
    return Response(status_code=204)
