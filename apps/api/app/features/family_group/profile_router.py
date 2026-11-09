"""가족 프로필·별명·관리자 지정(PR 4-C) 엔드포인트. family_group 라우터에 포함되어 /family-group 아래로 열린다.

그룹은 요청에서 받지 않고 current_group_id(실제 멤버십까지 확인)로만 정한다."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import profile_service, service
from .models import User
from .profile_schemas import NicknameIn, NicknameOut, ProfileIn, RoleIn
from .schemas import GroupOut

router = APIRouter()


@router.put("/groups/me/profile", response_model=GroupOut)
def update_profile(
    body: ProfileIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> GroupOut:
    """내 표시 이름·가족 관계를 바꾼다(내 멤버십만). 보낸 항목만 바뀌고 null 은 지운다."""
    profile_service.update_my_profile(db, user, group_id, body)
    return service.group_out_by_id(db, group_id, user.id)


@router.put("/groups/members/{user_id}/role", response_model=GroupOut)
def change_role(
    user_id: str,
    body: RoleIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> GroupOut:
    """구성원을 관리자(admin)로 지정하거나 구성원(member)으로 되돌린다. 소유자만, 소유자 본인은 대상이 될 수 없다."""
    profile_service.change_member_role(db, user, group_id, user_id, body)
    return service.group_out_by_id(db, group_id, user.id)


@router.post("/groups/me/leave", status_code=204)
def leave_group(
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Response:
    """내가 현재 가족 그룹을 나간다. 소유자는 다른 구성원이 있으면 나갈 수 없다(400 cannot_leave_owner). 구성원이 소유자 혼자뿐이면 나갈 수 있고, 그때는 가족의 모든 데이터(채팅·사진 파일·일정·가계·기록·가입 요청·초대 코드)가 한 트랜잭션에서 지워진다(되돌릴 수 없다)."""
    profile_service.leave_group(db, user, group_id)
    return Response(status_code=204)


@router.get("/groups/me/nicknames", response_model=list[NicknameOut])
def list_nicknames(
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[NicknameOut]:
    """내가 다른 구성원에게 붙인 별명·메모(내가 쓴 것만)."""
    return [
        NicknameOut(target_user_id=r.target_user_id, nickname=r.nickname, memo=r.memo)
        for r in profile_service.list_my_nicknames(db, user, group_id)
    ]


@router.put("/groups/me/nicknames/{target_user_id}", response_model=NicknameOut)
def set_nickname(
    target_user_id: str,
    body: NicknameIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> NicknameOut:
    """별명·메모를 정한다. 둘 다 비우면 지운다. 나에게만 보이고 다른 사람에게는 영향이 없다."""
    row = profile_service.set_nickname(db, user, group_id, target_user_id, body)
    return NicknameOut(
        target_user_id=target_user_id,
        nickname=row.nickname if row else None,
        memo=row.memo if row else None,
    )
